"""Sandbox management over Docker Engine, Firecracker microVMs, or Lima VMs."""

import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional

from e2b_dropin.agent_bootstrap import agentlib_e2b_start_script, container_has_agentlib_e2b_server
from .container_manager import ContainerManager, ContainerConfig
from .envd_template_bake import (
    bake_envd_guest_into_container,
    container_has_baked_envd,
    envd_guest_tarball_bytes,
    should_embed_envd_at_template_build,
    uvicorn_envd_start_script,
)
from .firecracker_plane import FC_WARM_DOCKERLESS_MARKER
from .lima_plane import LIMA_WARM_DOCKERLESS_MARKER
from .template_image import resolve_sandbox_image
from database import Database

if TYPE_CHECKING:
    from .protocols import SandboxExecutionPlane

logger = logging.getLogger(__name__)


def _resolve_sandbox_image(template_id: Optional[str]) -> str:
    return resolve_sandbox_image(template_id)


def _docker_engine_for_template_build(config: Any) -> Optional[ContainerManager]:
    """Docker ``runc`` client used to build Dockerfile templates when sandboxes run on Firecracker."""
    dh = (getattr(config, "DOCKER_HOST", None) or "").strip()
    if dh:
        os.environ["DOCKER_HOST"] = dh
    cm = ContainerManager(oci_runtime=None)
    return cm if cm.check_docker() else None


class SandboxManager:
    """Manages sandbox lifecycle."""

    instance: Optional["SandboxManager"] = None

    def __init__(
        self,
        db: Database,
        execution: Optional["SandboxExecutionPlane"] = None,
    ):
        self.db = db
        if execution is None:
            from config import get_config
            from .execution_backend import build_execution_backend

            execution = build_execution_backend(get_config())
        self.execution = execution
        from config import get_config

        self._config = get_config()
        # Serialize file + command I/O per sandbox so parallel agent tools (e.g. write_file ||
        # execute) cannot reorder at the API layer.
        self._sandbox_io_guard = threading.Lock()
        self._sandbox_io_locks: Dict[str, threading.Lock] = {}
        self._template_build_guard = threading.Lock()
        self._template_build_locks: Dict[str, threading.Lock] = {}
        self.warm_pool: Optional[Any] = None
        try:
            cfg = self._config
            kind = self.execution.get_backend_kind()
            if cfg.SANDBOX_WARM_POOL_SIZE > 0 and kind == "lima":
                logger.warning(
                    "SANDBOX_WARM_POOL_SIZE=%s is not supported with Lima per-VM sandboxes; warm pool disabled.",
                    cfg.SANDBOX_WARM_POOL_SIZE,
                )
            elif cfg.SANDBOX_WARM_POOL_SIZE > 0:
                from .warm_sandbox_pool import MultiWarmSandboxPool

                self.warm_pool = MultiWarmSandboxPool(self, cfg)
                self.warm_pool.start()
        except Exception as ex:  # noqa: BLE001
            logger.warning("Warm sandbox pool not started: %s", ex)

    def _template_lock(self, template_id: str) -> threading.Lock:
        with self._template_build_guard:
            if template_id not in self._template_build_locks:
                self._template_build_locks[template_id] = threading.Lock()
            return self._template_build_locks[template_id]

    def discard_from_warm_pool(self, sandbox_id: str) -> None:
        """If ``sandbox_id`` was sitting in the warm deque, remove it (e.g. before kill)."""
        pool = getattr(self, "warm_pool", None)
        if pool is not None:
            pool.discard(sandbox_id)

    def _sandbox_io_lock(self, sandbox_id: str) -> threading.Lock:
        with self._sandbox_io_guard:
            if sandbox_id not in self._sandbox_io_locks:
                self._sandbox_io_locks[sandbox_id] = threading.Lock()
            return self._sandbox_io_locks[sandbox_id]

    @property
    def container_mgr(self) -> ContainerManager:
        """Docker Engine manager (``SANDBOX_ENGINE=docker`` only)."""
        if not isinstance(self.execution, ContainerManager):
            raise TypeError(
                "SandboxManager.container_mgr is only valid when SANDBOX_ENGINE=docker; "
                "use self.execution for the active plane."
            )
        return self.execution

    def get_execution_kind(self) -> str:
        return self.execution.get_backend_kind()

    def describe_docker_workload_blocker(self) -> Optional[str]:
        """If Docker/gVisor cannot run containers, return a short diagnostic string for HTTP 503 / health."""
        kind = self.execution.get_backend_kind()
        if kind not in ("docker", "gvisor"):
            return None
        if not isinstance(self.execution, ContainerManager):
            return None
        return self.execution.describe_docker_unavailable()

    def get_e2b_agent_upstream_ws_uri(self, sandbox_id: str) -> Optional[str]:
        """``ws://<host>:<port>/`` for Docker sandboxes; ``None`` if unsupported or not running."""
        kind = self.execution.get_backend_kind()
        if kind not in ("docker", "gvisor"):
            return None
        if not isinstance(self.execution, ContainerManager):
            return None
        row = self.db.get_sandbox((sandbox_id or "").strip())
        if not row:
            return None
        cid = (row.get("container_id") or "").strip()
        if not cid or not self.execution.is_container_running(cid):
            return None
        port = max(1, min(65535, int(getattr(self._config, "E2B_DROPIN_AGENT_PORT", 8765))))
        meta = row.get("metadata") or {}
        hp = meta.get("e2b_agent_host_tcp_port")
        if hp is not None and str(hp).strip() != "":
            try:
                hpi = int(hp)
            except (TypeError, ValueError):
                hpi = 0
            if 1 <= hpi <= 65535:
                host = (getattr(self._config, "E2B_DROPIN_UPSTREAM_WS_HOST", None) or "127.0.0.1").strip() or "127.0.0.1"
                return f"ws://{host}:{hpi}/"
        ip = self.execution.get_container_internal_ipv4(cid)
        if not ip:
            return None
        return f"ws://{ip}:{port}/"

    def mint_e2b_traffic_token(self, sandbox_id: str) -> str:
        from e2b_dropin.tokens import mint_traffic_token

        secret = (getattr(self._config, "E2B_DROPIN_WS_SECRET", None) or "").strip()
        port = int(getattr(self._config, "E2B_DROPIN_AGENT_PORT", 8765))
        ttl = int(getattr(self._config, "E2B_DROPIN_TOKEN_TTL_SEC", 7200))
        return mint_traffic_token(secret, sandbox_id=sandbox_id.strip(), agent_port=port, ttl_sec=ttl)

    def get_envd_connection_ex(
        self, sandbox_id: str
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Like ``get_envd_connection`` but on failure returns ``(None, short_reason)`` for HTTP 503 hints.

        Reasons intentionally omit tokens and host ports.
        """
        sid = (sandbox_id or "").strip()
        kind = self.execution.get_backend_kind()
        if kind not in ("docker", "gvisor"):
            return None, f"runtime {kind!r} does not support published envd (need docker or gvisor)"
        if not isinstance(self.execution, ContainerManager):
            return None, "execution backend is not Docker/gVisor"
        row = self.db.get_sandbox(sid)
        if not row:
            return None, "sandbox not found"
        cid = (row.get("container_id") or "").strip()
        if not cid or not self.execution.is_container_running(cid):
            return None, "container missing or not running"
        meta = row.get("metadata") or {}
        tok = (meta.get("envd_access_token") or "").strip()
        hp = meta.get("envd_host_tcp_port")
        if not tok and hp is None:
            return (
                None,
                "no envd metadata on this sandbox (create with API env ENVD_PUBLISH_PORT=true, then recreate); "
                "existing sandboxes keep whatever was configured at create time",
            )
        if hp is None:
            return None, "envd_host_tcp_port missing (port publish failed at create or metadata lost)"
        if not tok:
            return None, "envd_access_token missing in metadata"
        try:
            hpi = int(hp)
        except (TypeError, ValueError):
            return None, "envd_host_tcp_port is not a valid integer"
        if not (1 <= hpi <= 65535):
            return None, "envd_host_tcp_port out of range"
        host = (getattr(self._config, "ENVD_UPSTREAM_HTTP_HOST", None) or "127.0.0.1").strip() or "127.0.0.1"
        port = max(1, min(65535, int(getattr(self._config, "ENVD_PORT", 49983))))
        return (
            {
                "sandbox_id": sid,
                "envd_port": port,
                "http_base_url": f"http://{host}:{hpi}",
                "access_token": tok,
            },
            None,
        )

    def get_envd_connection(self, sandbox_id: str) -> Optional[Dict[str, Any]]:
        """Return ``http_base_url``, ``access_token``, ``envd_port`` for Docker sandboxes with published envd."""
        info, _reason = self.get_envd_connection_ex(sandbox_id)
        return info

    def _bootstrap_envd_daemon(self, sandbox_id: str, container_id: str, port: int) -> None:
        """Start guest envd: if the template image already embeds ``envd_guest``, only spawn uvicorn."""
        if not isinstance(self.execution, ContainerManager):
            return
        p = max(1, min(65535, int(port)))
        pip_to = float(getattr(self._config, "ENVD_BOOTSTRAP_PIP_TIMEOUT_SEC", 300.0) or 300.0)
        with self._sandbox_io_lock(sandbox_id):
            if container_has_baked_envd(self.execution.run_command, container_id):
                start = uvicorn_envd_start_script(p)
                st = self.execution.run_command(container_id, start, timeout=120.0)
                if int(st.get("exit_code") or 0) != 0:
                    logger.warning(
                        "envd start (baked image): daemon did not listen on :%s sandbox=%s stderr=%s",
                        p,
                        sandbox_id,
                        (st.get("stderr") or "")[:2500],
                    )
                else:
                    logger.info("envd start (baked image): sandbox %s guest listening on tcp/%s", sandbox_id, p)
                return

            tb = envd_guest_tarball_bytes()
            if not tb:
                logger.warning("envd auto-start: api_server/envd_guest missing on API host")
                return
            if not self.execution.put_archive_to_container(container_id, "/opt", tb):
                logger.warning("envd auto-start: put_archive failed sandbox=%s", sandbox_id)
                return
            pip = self.execution.run_command(
                container_id,
                "python3 -m pip install -q -r /opt/envd_guest/requirements.txt",
                timeout=pip_to,
            )
            if int(pip.get("exit_code") or 0) != 0:
                logger.warning(
                    "envd auto-start: pip install failed sandbox=%s stderr=%s",
                    sandbox_id,
                    (pip.get("stderr") or "")[:2500],
                )
                return
            start = uvicorn_envd_start_script(p)
            st = self.execution.run_command(container_id, start, timeout=120.0)
            if int(st.get("exit_code") or 0) != 0:
                logger.warning(
                    "envd auto-start: daemon did not listen on :%s sandbox=%s stderr=%s",
                    p,
                    sandbox_id,
                    (st.get("stderr") or "")[:2500],
                )
            else:
                logger.info("envd auto-start: sandbox %s guest listening on tcp/%s", sandbox_id, p)

    def _bootstrap_e2b_agent_server(self, sandbox_id: str, container_id: str, port: int) -> None:
        """Start ``agentlib-e2b-server`` when the template image ships it (drop-in WS on ``port``)."""
        if not isinstance(self.execution, ContainerManager):
            return
        p = max(1, min(65535, int(port)))
        with self._sandbox_io_lock(sandbox_id):
            if not container_has_agentlib_e2b_server(self.execution.run_command, container_id):
                logger.info(
                    "E2B agent auto-start skipped sandbox=%s: agentlib-e2b-server not in image",
                    sandbox_id,
                )
                return
            start = agentlib_e2b_start_script(p)
            st = self.execution.run_command(container_id, start, timeout=120.0)
            if int(st.get("exit_code") or 0) != 0:
                logger.warning(
                    "E2B agent auto-start: daemon did not listen on :%s sandbox=%s stderr=%s",
                    p,
                    sandbox_id,
                    (st.get("stderr") or "")[:2500],
                )
            else:
                logger.info(
                    "E2B agent auto-start: sandbox %s guest listening on tcp/%s",
                    sandbox_id,
                    p,
                )

    def create_sandbox(
        self,
        template_id: str = "python:3.11",
        metadata: Optional[Dict[str, Any]] = None,
        cpu_limit: str = "1",
        memory_limit: str = "512m",
        timeout: int = 3600,
        from_snapshot_image: Optional[str] = None,
    ) -> Optional[str]:
        """Create new sandbox, optionally from a prior ``docker commit`` image or warm pool."""
        snap = (from_snapshot_image or "").strip()
        if snap:
            return self._create_sandbox_fresh(
                template_id=template_id,
                metadata=metadata,
                cpu_limit=cpu_limit,
                memory_limit=memory_limit,
                timeout=timeout,
                from_snapshot_image=snap,
            )

        tid = (template_id or "").strip()
        tpl = self.db.get_sandbox_template(tid) if tid else None

        pool = getattr(self, "warm_pool", None)

        # With warm pool enabled, bare Docker image refs (no prior POST /templates row) are
        # auto-registered so the first create can build warm_snapshot_image + ensure_pool_for.
        # Skip the configured default pool template_id so MultiWarm.start()'s base-image segment
        # is not replaced by a conflicting registered-template path for the same key.
        warm_pool_default_tid = (
            self._config.SANDBOX_WARM_POOL_TEMPLATE_ID or self._config.DEFAULT_TEMPLATE
        ).strip()
        if (
            tid
            and tpl is None
            and int(self._config.SANDBOX_WARM_POOL_SIZE) > 0
            and tid != warm_pool_default_tid
        ):
            base_image = _resolve_sandbox_image(tid)
            self.db.upsert_sandbox_template(
                tid,
                base_image,
                {},
                "",
                20,
                "",
            )
            tpl = self.db.get_sandbox_template(tid)
            logger.info(
                "Auto-registered logical template template_id=%r base_image=%r (warm pool)",
                tid,
                base_image,
            )

        # First use of the configured default template (e.g. python:3.11): register + warm snapshot so
        # ``ENVD_EMBED_AT_TEMPLATE_BUILD`` can bake envd into the committed image without a prior POST /templates.
        if (
            tid
            and tpl is None
            and should_embed_envd_at_template_build(self._config)
            and isinstance(self.execution, ContainerManager)
            and self.execution.get_backend_kind() in ("docker", "gvisor")
            and tid == (self._config.DEFAULT_TEMPLATE or "").strip()
        ):
            base_image = _resolve_sandbox_image(tid)
            self.db.upsert_sandbox_template(
                tid,
                base_image,
                {},
                "",
                20,
                "",
            )
            tpl = self.db.get_sandbox_template(tid)
            logger.info(
                "Auto-registered default template_id=%r base_image=%r (envd template embed)",
                tid,
                base_image,
            )

        if tpl:
            if not tpl.get("warm_snapshot_image"):
                if not self._build_registered_template_snapshot(tid):
                    return None
                tpl = self.db.get_sandbox_template(tid) or tpl
            warm_img = (tpl.get("warm_snapshot_image") or "").strip()
            # Parsed Dockerfile builds store the committed OCI ref as ``base_image`` and should mirror
            # ``warm_snapshot_image``. If the snapshot column is still empty (e.g. failed UPDATE),
            # using ``_resolve_sandbox_image(template_id)`` would start ``newp1`` as a literal image
            # name while **env** still comes from the template row — looks like "right env, no /app".
            if not warm_img:
                bi = (tpl.get("base_image") or "").strip()
                if bi and bi != tid and (":" in bi or "/" in bi):
                    warm_img = bi
                    logger.warning(
                        "Template %r: warm_snapshot_image missing; using base_image %r for sandbox image",
                        tid,
                        bi,
                    )
            cfg = self._config
            if pool is not None and cfg.SANDBOX_WARM_POOL_SIZE > 0 and warm_img:
                pool.ensure_pool_for(tid, cpu_limit, memory_limit, int(timeout), warm_img)
            if pool is not None:
                sid = pool.try_acquire(tid, metadata, cpu_limit, memory_limit, int(timeout))
                if sid:
                    return sid
            return self._create_sandbox_fresh(
                template_id=tid,
                metadata=metadata,
                cpu_limit=cpu_limit,
                memory_limit=memory_limit,
                timeout=timeout,
                from_snapshot_image=warm_img or None,
            )

        if pool is not None:
            sid = pool.try_acquire(tid, metadata, cpu_limit, memory_limit, int(timeout))
            if sid:
                return sid
        return self._create_sandbox_fresh(
            template_id=template_id,
            metadata=metadata,
            cpu_limit=cpu_limit,
            memory_limit=memory_limit,
            timeout=timeout,
            from_snapshot_image=None,
        )

    def sync_warm_pool_default_segment(self, template_id: str, warm_ref: str) -> None:
        """Rebuild the **default** warm-pool segment to use ``warm_ref`` when it matches pool template_id.

        Without this, ``MultiWarmSandboxPool.start()`` provisions from ``from_snapshot_image=None``
        (raw ``python:3.11``) while ``POST /sandboxes`` uses ``warm_snapshot_image`` — different images.
        """
        pool = getattr(self, "warm_pool", None)
        if pool is None or int(getattr(self._config, "SANDBOX_WARM_POOL_SIZE", 0) or 0) <= 0:
            return
        pid = (self._config.SANDBOX_WARM_POOL_TEMPLATE_ID or self._config.DEFAULT_TEMPLATE).strip()
        if (template_id or "").strip() != pid:
            return
        ref = (warm_ref or "").strip()
        if not ref or ref in (FC_WARM_DOCKERLESS_MARKER, LIMA_WARM_DOCKERLESS_MARKER):
            return
        pool.ensure_pool_for(
            pid,
            self._config.SANDBOX_WARM_POOL_CPU or self._config.DEFAULT_CPU_LIMIT,
            self._config.SANDBOX_WARM_POOL_MEMORY or self._config.DEFAULT_MEMORY_LIMIT,
            int(self._config.SANDBOX_WARM_POOL_TIMEOUT or self._config.DEFAULT_TIMEOUT),
            ref,
        )
        logger.info(
            "Warm pool default segment now uses warm_snapshot_image for template_id=%r",
            pid,
        )

    def _build_registered_template_snapshot(self, template_id: str) -> bool:
        """One-time: base image + env + ``start_cmd`` + settle, then ``docker commit``."""
        if self.execution.get_backend_kind() == "firecracker":
            self.db.set_template_warm_snapshot(template_id, FC_WARM_DOCKERLESS_MARKER, None)
            logger.info(
                "Firecracker engine: skipping Docker-based template snapshot for %r (marker %s)",
                template_id,
                FC_WARM_DOCKERLESS_MARKER,
            )
            return True
        if self.execution.get_backend_kind() == "lima":
            self.db.set_template_warm_snapshot(template_id, LIMA_WARM_DOCKERLESS_MARKER, None)
            logger.info(
                "Lima isolation: skipping Docker-based template snapshot for %r (marker %s)",
                template_id,
                LIMA_WARM_DOCKERLESS_MARKER,
            )
            return True
        lock = self._template_lock(template_id)
        with lock:
            row = self.db.get_sandbox_template(template_id)
            if not row:
                return False
            if row.get("warm_snapshot_image"):
                return True

            cfg = self._config
            name = f"tpl-build-{uuid.uuid4().hex[:10]}"
            env = dict(row.get("env") or {})
            build_timeout = max(int(row.get("settle_seconds") or 20) + 900, 1800)
            cfg_build = ContainerConfig(
                image=row["base_image"],
                cpu_limit=cfg.TEMPLATE_BUILD_CPU,
                memory_limit=cfg.TEMPLATE_BUILD_MEMORY,
                timeout=build_timeout,
                environment=env if env else None,
            )
            cid = self.execution.create_container(name, cfg_build)
            if not cid:
                self.db.set_template_build_error(template_id, "create_container failed for template build")
                return False
            try:
                sc = (row.get("start_cmd") or "").strip()
                if sc:
                    r = self.execution.run_command(cid, sc, timeout=3600.0)
                    ec = int(r.get("exit_code") or 0)
                    if ec != 0:
                        logger.warning(
                            "Template %s start_cmd non-zero exit=%s stderr=%s",
                            template_id,
                            ec,
                            (r.get("stderr") or "")[:2000],
                        )
                settle = max(0, min(int(row.get("settle_seconds") or 20), 600))
                time.sleep(settle)
                ready = (row.get("ready_cmd") or "").strip()
                if ready:
                    deadline = time.monotonic() + max(
                        30.0, float(getattr(cfg, "TEMPLATE_READY_TIMEOUT_SEC", 600) or 600)
                    )
                    poll_s = 2.0
                    ok_ready = False
                    while time.monotonic() < deadline:
                        rr = self.execution.run_command(cid, ready, timeout=120.0)
                        if int(rr.get("exit_code") or 0) == 0:
                            ok_ready = True
                            break
                        time.sleep(poll_s)
                    if not ok_ready:
                        self.db.set_template_build_error(
                            template_id,
                            "ready_cmd did not exit 0 before TEMPLATE_READY_TIMEOUT_SEC",
                        )
                        return False
                if should_embed_envd_at_template_build(cfg) and isinstance(self.execution, ContainerManager):
                    pt = float(getattr(cfg, "ENVD_BOOTSTRAP_PIP_TIMEOUT_SEC", 300.0) or 300.0)
                    bake_envd_guest_into_container(
                        put_archive_to_container=self.execution.put_archive_to_container,
                        run_command=self.execution.run_command,
                        container_id=cid,
                        pip_timeout_sec=pt,
                    )
                repo = (cfg.SANDBOX_SNAPSHOT_REPO or "mysandbox-snap").strip().lower().replace("/", "-") or "mysandbox-snap"
                tag_raw = f"tpl-{template_id}-{uuid.uuid4().hex[:10]}"
                tag = re.sub(r"[^a-z0-9._-]", "-", tag_raw.lower())[:120] or "tpl"
                commit_fn = getattr(self.execution, "commit_filesystem_snapshot", None)
                if not callable(commit_fn):
                    self.db.set_template_build_error(template_id, "commit_filesystem_snapshot unavailable")
                    return False
                image_ref = commit_fn(cid, repo, tag)
                if not image_ref:
                    self.db.set_template_build_error(template_id, "docker commit failed")
                    return False
                self.db.set_template_warm_snapshot(template_id, image_ref, None)
                logger.info("Template %s warm snapshot: %s", template_id, image_ref)
                self.sync_warm_pool_default_segment(template_id, image_ref)
                return True
            finally:
                self.execution.kill_container(cid, force=True)

    def build_template_from_dockerfile_parsed(
        self,
        template_id: str,
        dockerfile: str,
        env: Optional[Dict[str, Any]],
        start_cmd: str,
        settle_seconds: int,
        ready_cmd: str,
        build_args: Optional[Dict[str, str]],
        context_tar_gzip: Optional[bytes],
        image_tag: Optional[str],
    ) -> Dict[str, Any]:
        """Parse Dockerfile, apply ``RUN``/``COPY``/… inside a build container, ``docker commit``, set warm snapshot.

        Same end state as ``_build_registered_template_snapshot`` (``warm_snapshot_image`` populated) so
        ``POST /sandboxes`` and the **warm pool** reuse this image without a second bake.
        """
        import io as _io
        import tarfile as _tarfile

        from .template_dockerfile_builder import (
            apply_dockerfile_inside_container,
            extract_base_image_from_dockerfile,
        )

        kind = self.execution.get_backend_kind()
        if kind == "lima":
            raise RuntimeError(
                "Parsed Dockerfile template build requires Docker Engine (Lima VM isolation has no Docker build path)."
            )
        plane: Any = self.execution
        if kind == "firecracker":
            docker_cm = _docker_engine_for_template_build(self._config)
            if docker_cm is None:
                raise RuntimeError(
                    "Firecracker engine: Dockerfile template build needs Docker Engine on this host "
                    "(set DOCKER_HOST, ensure `docker info` works, and keep `docker` on PATH)."
                )
            plane = docker_cm
        if not hasattr(plane, "put_archive_to_container"):
            raise RuntimeError("Parsed Dockerfile builds require Docker ContainerManager.put_archive_to_container")

        base_image = extract_base_image_from_dockerfile(dockerfile)
        cfg = self._config
        tmp = Path(tempfile.mkdtemp(prefix="tpl-parse-"))
        cid: Optional[str] = None
        merge_env = dict(env or {})
        merged_template_env = dict(merge_env)
        image_ref: Optional[str] = None
        try:
            if context_tar_gzip:
                buf = _io.BytesIO(context_tar_gzip)
                with _tarfile.open(fileobj=buf, mode="r:gz") as tf:
                    try:
                        tf.extractall(tmp, filter="data")
                    except TypeError:
                        tf.extractall(tmp)

            name = f"tpl-parse-{uuid.uuid4().hex[:10]}"
            build_timeout = max(int(settle_seconds or 0) + 900, 1800)
            cfg_build = ContainerConfig(
                image=base_image,
                cpu_limit=cfg.TEMPLATE_BUILD_CPU,
                memory_limit=cfg.TEMPLATE_BUILD_MEMORY,
                timeout=build_timeout,
                environment=merge_env if merge_env else None,
            )
            cid = plane.create_container(name, cfg_build)
            if not cid:
                raise RuntimeError("create_container failed for Dockerfile template build")

            def _put(parent: str, data: bytes) -> bool:
                fn = getattr(plane, "put_archive_to_container", None)
                if not callable(fn):
                    return False
                return bool(fn(cid, parent, data))

            _, env_from_dockerfile = apply_dockerfile_inside_container(
                run_command=plane.run_command,
                put_archive_bytes=_put,
                container_id=cid,
                dockerfile=dockerfile,
                context_dir=tmp,
                build_args=build_args,
                run_timeout=float(getattr(cfg, "TEMPLATE_DOCKERFILE_RUN_TIMEOUT_SEC", 7200.0) or 7200.0),
            )
            merged_template_env.update(env_from_dockerfile)

            if should_embed_envd_at_template_build(cfg):
                pa = getattr(plane, "put_archive_to_container", None)
                if callable(pa):
                    pt = float(getattr(cfg, "ENVD_BOOTSTRAP_PIP_TIMEOUT_SEC", 300.0) or 300.0)
                    bake_envd_guest_into_container(
                        put_archive_to_container=pa,
                        run_command=plane.run_command,
                        container_id=cid,
                        pip_timeout_sec=pt,
                    )

            sc = (start_cmd or "").strip()
            if sc:
                r = plane.run_command(
                    cid,
                    sc,
                    timeout=3600.0,
                    env=merged_template_env if merged_template_env else None,
                )
                if int(r.get("exit_code") or 0) != 0:
                    logger.warning(
                        "Template %s post-Dockerfile start_cmd non-zero exit=%s",
                        template_id,
                        r.get("exit_code"),
                    )

            settle = max(0, min(int(settle_seconds or 20), 600))
            time.sleep(settle)
            ready = (ready_cmd or "").strip()
            if ready:
                deadline = time.monotonic() + max(
                    30.0, float(getattr(cfg, "TEMPLATE_READY_TIMEOUT_SEC", 600) or 600)
                )
                ok_ready = False
                while time.monotonic() < deadline:
                    rr = plane.run_command(
                        cid,
                        ready,
                        timeout=120.0,
                        env=merged_template_env if merged_template_env else None,
                    )
                    if int(rr.get("exit_code") or 0) == 0:
                        ok_ready = True
                        break
                    time.sleep(2.0)
                if not ok_ready:
                    raise RuntimeError("ready_cmd did not succeed within TEMPLATE_READY_TIMEOUT_SEC")

            repo_default = (cfg.SANDBOX_SNAPSHOT_REPO or "mysandbox-snap").strip().lower().replace("/", "-") or "mysandbox-snap"
            full_tag = (image_tag or "").strip()
            if full_tag and ":" in full_tag:
                rep, tg = full_tag.rsplit(":", 1)
                rep = rep.strip() or repo_default
                tg = re.sub(r"[^a-z0-9._-]", "-", (tg or "latest").lower())[:120] or "latest"
            elif full_tag:
                rep, tg = full_tag, "latest"
            else:
                rep = repo_default
                tg = re.sub(
                    r"[^a-z0-9._-]",
                    "-",
                    f"tpl-{template_id}-{uuid.uuid4().hex[:10]}".lower(),
                )[:120] or "tpl"

            commit_fn = getattr(plane, "commit_filesystem_snapshot", None)
            if not callable(commit_fn):
                raise RuntimeError("commit_filesystem_snapshot unavailable")
            image_ref = commit_fn(cid, rep, tg)
            if not image_ref:
                raise RuntimeError("docker commit failed after parsed Dockerfile build")
        finally:
            if cid:
                try:
                    plane.kill_container(cid, force=True)
                except Exception:
                    pass
            shutil.rmtree(tmp, ignore_errors=True)

        if not image_ref:
            raise RuntimeError("Dockerfile template build produced no image")

        warm_ref = image_ref
        if self.execution.get_backend_kind() == "firecracker":
            from .fc_dockerfile_rootfs_export import materialize_firecracker_template_ext4

            warm_ref = materialize_firecracker_template_ext4(
                self._config, oci_image_ref=image_ref, template_id=template_id
            )

        self.db.upsert_sandbox_template(
            template_id,
            image_ref,
            merged_template_env,
            "",
            0,
            "",
        )
        if not self.db.set_template_warm_snapshot(template_id, warm_ref, None):
            raise RuntimeError(
                f"set_template_warm_snapshot failed for template_id={template_id!r} "
                f"(warm_ref={warm_ref!r}); SQLite row missing after upsert — check DATABASE_PATH / DB."
            )
        logger.info("Template %s (parsed Dockerfile) warm snapshot: %s", template_id, warm_ref)
        self.sync_warm_pool_default_segment(template_id, warm_ref)
        return self.db.get_sandbox_template(template_id) or {}

    def materialize_firecracker_rootfs_from_oci(self, oci_image_ref: str, template_id: str) -> str:
        """Export a built OCI tag to a host ``.ext4`` for Firecracker (see ``fc_dockerfile_rootfs_export``)."""
        from .fc_dockerfile_rootfs_export import materialize_firecracker_template_ext4

        return materialize_firecracker_template_ext4(
            self._config, oci_image_ref=oci_image_ref, template_id=template_id
        )

    def _create_sandbox_fresh(
        self,
        template_id: str = "python:3.11",
        metadata: Optional[Dict[str, Any]] = None,
        cpu_limit: str = "1",
        memory_limit: str = "512m",
        timeout: int = 3600,
        from_snapshot_image: Optional[str] = None,
    ) -> Optional[str]:
        """Create a brand-new sandbox (never taken from the warm pool)."""
        sandbox_id = f"sb-{uuid.uuid4().hex[:16]}"
        container_name = f"sandbox-{uuid.uuid4().hex[:8]}"

        snap = (from_snapshot_image or "").strip()
        root_override: Optional[str] = None
        fc_bundle_ref: Optional[str] = None
        if self.execution.get_backend_kind() == "firecracker":
            image = (template_id or "").strip() or "firecracker"
            if snap:
                if snap == FC_WARM_DOCKERLESS_MARKER:
                    snap = ""
                elif snap.startswith("fc-bundle:"):
                    fc_bundle_ref = snap
                    snap = ""
                elif snap.endswith(".ext4") or os.path.isfile(snap):
                    root_override = snap
                else:
                    logger.warning(
                        "Firecracker: ignoring docker image / snapshot ref %r (use host .ext4 path or fc-bundle:…)",
                        snap,
                    )
        elif self.execution.get_backend_kind() == "lima":
            image = (template_id or "").strip() or "lima"
            if snap and snap != LIMA_WARM_DOCKERLESS_MARKER:
                logger.warning(
                    "Lima: ignoring Docker image / snapshot ref %r (use LIMA_SANDBOX_TEMPLATE / template_id as template://…)",
                    snap,
                )
            snap = ""
        elif snap:
            image = snap
        else:
            image = _resolve_sandbox_image(template_id)
        runtime = self.execution.get_backend_kind()
        logger.info(
            "Creating sandbox %s runtime=%s template_id=%r image=%r (from_snapshot=%s)",
            sandbox_id,
            runtime,
            template_id,
            image,
            bool(snap),
        )

        tpl = self.db.get_sandbox_template((template_id or "").strip()) if template_id else None
        env_for_create: Optional[Dict[str, str]] = None
        if tpl:
            ev = dict(tpl.get("env") or {})
            if ev:
                env_for_create = ev

        agent_port_cfg = max(1, min(65535, int(getattr(self._config, "E2B_DROPIN_AGENT_PORT", 8765))))
        publish_agent = bool(
            isinstance(self.execution, ContainerManager)
            and getattr(self._config, "E2B_DROPIN_PUBLISH_AGENT_PORT", False)
        )

        envd_port_cfg = max(1, min(65535, int(getattr(self._config, "ENVD_PORT", 49983))))
        publish_envd = bool(
            isinstance(self.execution, ContainerManager) and getattr(self._config, "ENVD_PUBLISH_PORT", False)
        )
        envd_token: Optional[str] = None
        if publish_envd:
            envd_token = secrets.token_urlsafe(32)
            if env_for_create is None:
                env_for_create = {}
            env_for_create = {**env_for_create, "ENVD_ACCESS_TOKEN": envd_token}

        config = ContainerConfig(
            image=image,
            cpu_limit=cpu_limit,
            memory_limit=memory_limit,
            timeout=timeout,
            environment=env_for_create,
            rootfs_path=root_override,
            fc_bundle_ref=fc_bundle_ref,
            publish_e2b_agent_port=publish_agent,
            e2b_agent_port=agent_port_cfg,
            publish_envd_port=publish_envd,
            envd_port=envd_port_cfg,
        )

        container_id = self.execution.create_container(container_name, config)
        if not container_id:
            logger.error("Failed to create workload for sandbox %s", sandbox_id)
            return None

        self.db.create_sandbox(
            sandbox_id=sandbox_id,
            container_id=container_id,
            template_id=template_id,
            metadata=metadata,
            cpu_limit=cpu_limit,
            memory_limit=memory_limit,
            timeout=timeout,
            runtime=runtime,
        )

        if publish_agent and isinstance(self.execution, ContainerManager):
            hp = self.execution.get_container_tcp_host_port(container_id, agent_port_cfg)
            if hp:
                self.db.merge_sandbox_metadata(sandbox_id, {"e2b_agent_host_tcp_port": int(hp)})
                ws_host = (getattr(self._config, "E2B_DROPIN_UPSTREAM_WS_HOST", None) or "127.0.0.1").strip()
                logger.info(
                    "Sandbox %s E2B agent upstream will use ws://%s:%s/ (published host port -> container :%s)",
                    sandbox_id,
                    ws_host or "127.0.0.1",
                    hp,
                    agent_port_cfg,
                )
            else:
                logger.warning(
                    "Sandbox %s: E2B_DROPIN_PUBLISH_AGENT_PORT is enabled but no host port binding for tcp/%s",
                    sandbox_id,
                    agent_port_cfg,
                )
            if getattr(self._config, "E2B_DROPIN_AUTO_START_AGENT", True):
                self._bootstrap_e2b_agent_server(sandbox_id, container_id, agent_port_cfg)

        if publish_envd and isinstance(self.execution, ContainerManager) and envd_token:
            ehp = self.execution.get_container_tcp_host_port(container_id, envd_port_cfg)
            if ehp:
                self.db.merge_sandbox_metadata(
                    sandbox_id,
                    {"envd_host_tcp_port": int(ehp), "envd_access_token": envd_token},
                )
                hhost = (getattr(self._config, "ENVD_UPSTREAM_HTTP_HOST", None) or "127.0.0.1").strip()
                logger.info(
                    "Sandbox %s envd HTTP on http://%s:%s/ (host → container :%s)",
                    sandbox_id,
                    hhost or "127.0.0.1",
                    ehp,
                    envd_port_cfg,
                )
            else:
                logger.warning(
                    "Sandbox %s: ENVD_PUBLISH_PORT is enabled but no host port binding for tcp/%s",
                    sandbox_id,
                    envd_port_cfg,
                )
            if getattr(self._config, "ENVD_AUTO_START", True):
                self._bootstrap_envd_daemon(sandbox_id, container_id, envd_port_cfg)

        logger.info("Sandbox created: %s", sandbox_id)
        return sandbox_id

    def get_sandbox(self, sandbox_id: str) -> Optional[Dict[str, Any]]:
        """Get sandbox info."""
        return self.db.get_sandbox(sandbox_id)

    def get_sandbox_by_container(self, container_id: str) -> Optional[Dict[str, Any]]:
        """Get sandbox by container / instance ID."""
        return self.db.get_sandbox_by_container(container_id)

    def list_sandboxes(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List all sandboxes."""
        return self.db.list_sandboxes(limit=limit, offset=offset)

    def is_running(self, sandbox_id: str) -> bool:
        """Check if sandbox is running."""
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return False

        return self.execution.is_container_running(sandbox["container_id"])

    def create_filesystem_snapshot(
        self,
        sandbox_id: str,
        label: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Docker: ``docker commit`` into a new image, or Firecracker: full VM snapshot (``fc-bundle:`` ref)."""
        commit_fn = getattr(self.execution, "commit_filesystem_snapshot", None)
        if not callable(commit_fn):
            return None
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            logger.error("create_filesystem_snapshot: unknown sandbox %s", sandbox_id)
            return None
        cfg = self._config
        repo = (cfg.SANDBOX_SNAPSHOT_REPO or "mysandbox-snap").strip().lower().replace("/", "-")
        if not repo:
            repo = "mysandbox-snap"
        snap_uuid = uuid.uuid4().hex[:12]
        raw_tag = f"{sandbox_id}-{snap_uuid}"
        tag = re.sub(r"[^a-z0-9._-]", "-", raw_tag.lower())[:120] or "snap"
        image_ref = commit_fn(sandbox["container_id"], repo, tag)
        if not image_ref:
            return None
        snapshot_id = f"snap-{snap_uuid}"
        row = self.db.insert_sandbox_snapshot(snapshot_id, sandbox_id, image_ref, label)
        meta = dict(sandbox.get("metadata") or {})
        meta["last_snapshot_image"] = image_ref
        meta["last_snapshot_id"] = snapshot_id
        self.db.merge_sandbox_metadata(sandbox_id, meta)
        return row

    def list_filesystem_snapshots(self, sandbox_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.get_sandbox(sandbox_id):
            return []
        return self.db.list_sandbox_snapshots(sandbox_id, limit)

    def run_command(
        self,
        sandbox_id: str,
        command: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        user: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Run command in sandbox."""
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            logger.error("Sandbox not found: %s", sandbox_id)
            return None

        container_id = sandbox["container_id"]

        with self._sandbox_io_lock(sandbox_id):
            result = self.execution.run_command(
                container_id=container_id,
                command=command,
                cwd=cwd,
                env=env,
                timeout=timeout,
                user=user,
            )

        cmd_id = f"cmd-{uuid.uuid4().hex[:16]}"
        self.db.add_command_history(
            command_id=cmd_id,
            sandbox_id=sandbox_id,
            command=command,
            exit_code=result["exit_code"],
            stdout=result["stdout"],
            stderr=result["stderr"],
            pid=result["pid"],
            execution_time=0.0,
        )

        return result

    def iter_run_command_sse(
        self,
        sandbox_id: str,
        command: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        user: Optional[str] = None,
    ) -> Iterator[str]:
        """Server-Sent Events lines: ``data: <json>\\n\\n`` with stdout/stderr chunks and a final exit."""
        cmd_id = f"cmd-{uuid.uuid4().hex[:16]}"
        stdout_buf: List[str] = []
        stderr_buf: List[str] = []
        exit_code = -1
        started = time.time()

        def jline(obj: Dict[str, Any]) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            yield jline({"type": "error", "message": "Sandbox not found"})
            yield jline({"type": "exit", "exit_code": -1})
            return

        try:
            with self._sandbox_io_lock(sandbox_id):
                stream_fn = getattr(self.execution, "run_command_stream", None)
                if callable(stream_fn):
                    for ev in stream_fn(
                        sandbox["container_id"],
                        command,
                        cwd=cwd,
                        env=env,
                        timeout=timeout,
                        user=user,
                    ):
                        t = ev.get("type")
                        if t == "stdout":
                            stdout_buf.append(ev.get("chunk") or "")
                            yield jline({"type": "stdout", "chunk": ev.get("chunk") or ""})
                        elif t == "stderr":
                            stderr_buf.append(ev.get("chunk") or "")
                            yield jline({"type": "stderr", "chunk": ev.get("chunk") or ""})
                        elif t == "error":
                            yield jline(ev)
                        elif t == "exit":
                            exit_code = int(ev.get("exit_code", -1))
                            yield jline({"type": "exit", "exit_code": exit_code})
                else:
                    r = self.execution.run_command(
                        sandbox["container_id"],
                        command,
                        cwd=cwd,
                        env=env,
                        timeout=timeout,
                        user=user,
                    )
                    r = r or {}
                    if r.get("stdout"):
                        s = str(r["stdout"])
                        stdout_buf.append(s)
                        yield jline({"type": "stdout", "chunk": s})
                    if r.get("stderr"):
                        s = str(r["stderr"])
                        stderr_buf.append(s)
                        yield jline({"type": "stderr", "chunk": s})
                    exit_code = int(r.get("exit_code", -1))
                    yield jline({"type": "exit", "exit_code": exit_code})
        except Exception as e:  # noqa: BLE001
            logger.exception("iter_run_command_sse: %s", e)
            yield jline({"type": "error", "message": str(e)})
            yield jline({"type": "exit", "exit_code": -1})
            exit_code = -1
        finally:
            elapsed = time.time() - started
            self.db.add_command_history(
                cmd_id,
                sandbox_id,
                command,
                exit_code,
                "".join(stdout_buf),
                "".join(stderr_buf),
                -1,
                elapsed,
            )

    def read_file(self, sandbox_id: str, path: str) -> Optional[str]:
        """Read file from sandbox."""
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return None

        with self._sandbox_io_lock(sandbox_id):
            return self.execution.read_file(sandbox["container_id"], path)

    def write_file(self, sandbox_id: str, path: str, content: str) -> bool:
        """Write file to sandbox."""
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return False

        with self._sandbox_io_lock(sandbox_id):
            return self.execution.write_file(sandbox["container_id"], path, content)

    def list_files(self, sandbox_id: str, path: str = "/") -> Optional[list]:
        """List files in sandbox."""
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return None

        with self._sandbox_io_lock(sandbox_id):
            return self.execution.list_files(sandbox["container_id"], path)

    def delete_file(self, sandbox_id: str, path: str, recursive: bool = False) -> bool:
        """Delete file from sandbox."""
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return False

        with self._sandbox_io_lock(sandbox_id):
            return self.execution.delete_file(
                sandbox["container_id"], path, recursive=recursive
            )

    def create_directory(self, sandbox_id: str, path: str, mode: int = 0o755) -> bool:
        """Create directory in sandbox."""
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return False

        with self._sandbox_io_lock(sandbox_id):
            return self.execution.create_directory(sandbox["container_id"], path, mode)

    def get_metrics(self, sandbox_id: str) -> Optional[Dict[str, Any]]:
        """Get sandbox metrics."""
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return None

        stats = self.execution.get_container_stats(sandbox["container_id"])
        if not stats:
            return None

        return {
            "sandbox_id": sandbox_id,
            "memory_usage": stats["memory_usage"],
            "memory_limit": stats["memory_limit"],
            "cpu_percent": stats["cpu_percent"],
            "uptime": stats["uptime"],
        }

    def get_sandbox_lifecycle(self, sandbox_id: str) -> Optional[Dict[str, Any]]:
        """DB state plus whether the workload process is still running."""
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return None
        alive = self.execution.is_container_running(sandbox["container_id"])
        return {
            "sandbox_id": sandbox_id,
            "state": sandbox.get("state", "unknown"),
            "running": bool(alive),
            "timeout_seconds": int(sandbox["timeout"])
            if sandbox.get("timeout") is not None
            else None,
        }

    def refresh_sandbox_timeout(self, sandbox_id: str, timeout_seconds: int) -> bool:
        """Update stored lease timeout (E2B ``set_timeout``). Requires a running sandbox row."""
        sid = (sandbox_id or "").strip()
        if not sid:
            return False
        if not self.get_sandbox(sid):
            return False
        if not self.is_running(sid):
            return False
        ts = max(60, min(int(timeout_seconds), 604800))
        return bool(self.db.update_sandbox_timeout(sid, ts))

    def kill_sandbox(self, sandbox_id: str, force: bool = True) -> bool:
        """Kill sandbox."""
        self.discard_from_warm_pool(sandbox_id)
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            logger.error("Sandbox not found: %s", sandbox_id)
            return False

        container_id = sandbox["container_id"]

        if not self.execution.kill_container(container_id, force=force):
            logger.error("Failed to kill workload for sandbox %s", sandbox_id)
            return False

        self.db.update_sandbox_state(sandbox_id, "killed")
        self.db.delete_sandbox(sandbox_id)

        logger.info("Sandbox killed: %s", sandbox_id)
        return True

    def pause_sandbox(self, sandbox_id: str) -> bool:
        """Pause sandbox (Docker: freeze cgroup / ``docker pause``)."""
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return False

        if self.execution.pause_instance(sandbox["container_id"]):
            self.db.update_sandbox_state(sandbox_id, "paused")
            logger.info("Sandbox paused: %s", sandbox_id)
            return True
        logger.warning("Pause not applied for sandbox %s (unsupported or failed)", sandbox_id)
        return False

    def resume_sandbox(self, sandbox_id: str) -> bool:
        """Resume paused sandbox."""
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return False

        if self.execution.resume_instance(sandbox["container_id"]):
            self.db.update_sandbox_state(sandbox_id, "running")
            logger.info("Sandbox resumed: %s", sandbox_id)
            return True
        logger.warning("Resume not applied for sandbox %s (unsupported or failed)", sandbox_id)
        return False
