"""Sandbox management over Docker Engine or Firecracker microVMs."""

import json
import logging
import os
import re
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional

from .container_manager import ContainerManager, ContainerConfig
from .firecracker_plane import FC_WARM_DOCKERLESS_MARKER
from .template_image import resolve_sandbox_image
from database import Database

if TYPE_CHECKING:
    from .protocols import SandboxExecutionPlane

logger = logging.getLogger(__name__)

def _resolve_sandbox_image(template_id: Optional[str]) -> str:
    return resolve_sandbox_image(template_id)


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
            if cfg.SANDBOX_WARM_POOL_SIZE > 0:
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
            )
            tpl = self.db.get_sandbox_template(tid)
            logger.info(
                "Auto-registered logical template template_id=%r base_image=%r (warm pool)",
                tid,
                base_image,
            )

        if tpl:
            if not tpl.get("warm_snapshot_image"):
                if not self._build_registered_template_snapshot(tid):
                    return None
                tpl = self.db.get_sandbox_template(tid) or tpl
            warm_img = (tpl.get("warm_snapshot_image") or "").strip()
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
                return True
            finally:
                self.execution.kill_container(cid, force=True)

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

        config = ContainerConfig(
            image=image,
            cpu_limit=cpu_limit,
            memory_limit=memory_limit,
            timeout=timeout,
            environment=env_for_create,
            rootfs_path=root_override,
            fc_bundle_ref=fc_bundle_ref,
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
        """Docker: ``docker commit`` the container filesystem into a new local image."""
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
        }

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
