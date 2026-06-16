"""
E2B-style template builder for this project's REST API.

Mirrors the public shape of `e2b.Template` (fluent chain + `Template.build`) against
``POST /templates`` and ``POST /templates/from-dockerfile`` — not E2B's hosted builder.

Use :meth:`Template.from_dockerfile` for E2B-like **Dockerfile + whole directory context** without
per-file :meth:`Template.copy` staging (paths in the Dockerfile are relative to that directory).

You can also set the context root first: ``Template(file_context_path="/path/to/context").use_dockerfile(open("...").read())``
(equivalent to E2B's ``file_context_path`` constructor argument on ``Template``).

**Not available locally (by design / missing backend):**

- ``Template.build_in_background`` / ``Template.get_build_status`` — no job queue or build-id API.
- Streaming build logs to ``on_build_logs`` — the server does not emit E2B ``LogEntry`` streams;
  the callback is invoked with synthetic milestones only.
- ``cpu_count`` / ``memory_mb`` on ``build()`` — template build resources are server-side
  (``TEMPLATE_BUILD_CPU`` / ``TEMPLATE_BUILD_MEMORY`` in ``api_server`` config), not per-request.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import shlex
import tarfile
import warnings
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .api import APIEndpoints
from .api.sync import APIClient
from .config import DEFAULT_SDK_REQUEST_TIMEOUT
from .models import BuildInfo, TemplateDefinition

LogEntry = Dict[str, Any]


def default_build_logger() -> Callable[[LogEntry], None]:
    """E2B-compatible hook; logs simple ``LogEntry`` dicts to the ``my_sdk.template`` logger."""

    log = logging.getLogger("my_sdk.template")

    def _cb(entry: LogEntry) -> None:
        msg = entry.get("message") or entry.get("msg") or str(entry)
        lvl = (entry.get("level") or "info").lower()
        if lvl == "error":
            log.error("%s", msg)
        elif lvl == "warning":
            log.warning("%s", msg)
        else:
            log.info("%s", msg)

    return _cb


@dataclass(frozen=True)
class _ReadyTimeout:
    """Opaque marker from ``wait_for_timeout`` (E2B-style)."""

    ms: int


@dataclass(frozen=True)
class _ReadyPort:
    """Opaque marker from ``wait_for_port`` (E2B-style)."""

    port: int
    timeout_ms: int


def wait_for_timeout(ms: int) -> _ReadyTimeout:
    """E2B-style readiness hint after ``set_start_cmd`` (maps to a coarse ``ready_cmd``)."""
    return _ReadyTimeout(ms=max(0, int(ms)))


def wait_for_port(port: int, timeout_ms: int = 60_000) -> _ReadyPort:
    """Poll ``localhost:<port>`` until HTTP responds or timeout (maps to ``ready_cmd`` shell loop)."""
    return _ReadyPort(port=int(port), timeout_ms=max(1000, int(timeout_ms)))


def _ready_cmd_from_marker(marker: Union[_ReadyTimeout, _ReadyPort, str, None]) -> str:
    if marker is None:
        return ""
    if isinstance(marker, str):
        return marker
    if isinstance(marker, _ReadyTimeout):
        sec = max(0.0, marker.ms / 1000.0)
        # Approximation: ensure guest had time after start_cmd; real readiness should use wait_for_port.
        return f"sleep {shlex.quote(str(sec))} && true"
    if isinstance(marker, _ReadyPort):
        secs = max(1, marker.timeout_ms // 1000)
        p = int(marker.port)
        inner = (
            f"i=0; while [ $i -lt {secs} ]; do "
            f"curl -sf http://127.0.0.1:{p}/ >/dev/null 2>&1 && exit 0; "
            f"sleep 1; i=$((i+1)); done; exit 1"
        )
        return f"/bin/bash -c {shlex.quote(inner)}"
    return ""


class Template:
    """
    Fluent template definition (E2B-style method chaining).

    Call ``Template.build(template, name, api_url=..., api_key=...)`` to register on the API.

    **Dockerfile + context (E2B-like):** use ``Template().from_dockerfile("/path/Dockerfile")`` so the
    whole directory (default: the Dockerfile's directory) is sent as build context — no ``.copy()``.

    **Default context directory (E2B ``file_context_path``):** ``Template(file_context_path="/app")`` then
    ``.use_dockerfile(...)`` uses that folder as ``context_tar_gzip`` without an extra ``with_build_context`` call.
    """

    def __init__(self, *, file_context_path: Optional[str] = None) -> None:
        self._base_image: str = "python:3.11"
        self._workdir: str = "/"
        self._user: Optional[str] = None
        self._env: Dict[str, str] = {}
        self._run_cmds: List[str] = []
        self._copies: List[Tuple[str, str]] = []  # (host path, container path)
        self._start_cmd: str = ""
        self._start_readiness: Optional[Union[_ReadyTimeout, _ReadyPort, str]] = None
        self._settle_seconds: int = 20
        self._explicit_dockerfile: Optional[str] = None
        # Full-directory build context (gzip tar paths relative to this root). E2B-style ``from_dockerfile``.
        self._context_directory: Optional[str] = None
        self._build_args: Dict[str, str] = {}
        self._post_start_cmd: str = ""  # after image exists (API start_cmd on from-dockerfile)
        self._post_ready_cmd: str = ""
        self._post_settle: int = 20
        if file_context_path is not None:
            self.set_file_context_path(file_context_path)

    def set_file_context_path(self, directory: str) -> "Template":
        """Set the Docker build context root (E2B ``file_context_path``).

        After this, call :meth:`use_dockerfile` with a Dockerfile whose ``COPY`` paths are relative to
        this directory (you do **not** need :meth:`with_build_context` again for the same path).

        Mutually exclusive with :meth:`copy` (per-file staging).
        """
        if self._copies:
            raise ValueError(
                "set_file_context_path() cannot be used together with Template.copy(); "
                "use a full directory context or per-file .copy(), not both."
            )
        d = os.path.abspath(os.path.expanduser(directory.strip()))
        if not os.path.isdir(d):
            raise NotADirectoryError(f"file_context_path is not a directory: {d}")
        self._context_directory = d
        return self

    # --- Base images (E2B-style names) ---

    def from_base_image(self) -> "Template":
        """Default base image (``python:3.11``), matching E2B quickstart spirit."""
        self._base_image = "python:3.11"
        return self

    def from_python_image(self, version: str = "3.11") -> "Template":
        """``python:<version>`` Docker image."""
        self._base_image = f"python:{version.strip()}"
        return self

    def from_ubuntu_image(self, version: str = "22.04") -> "Template":
        """``ubuntu:<version>`` Docker image."""
        self._base_image = f"ubuntu:{version.strip()}"
        return self

    def from_docker_image(self, image: str) -> "Template":
        """Any pull-able Docker reference."""
        self._base_image = image.strip()
        return self

    # --- Files / commands ---

    def set_workdir(self, path: str) -> "Template":
        self._workdir = path.strip() or "/"
        return self

    def set_user(self, user: str) -> "Template":
        """Maps to Dockerfile ``USER`` when generating a Dockerfile."""
        self._user = user.strip() or None
        return self

    def set_envs(self, envs: Dict[str, str]) -> "Template":
        self._env = dict(envs or {})
        return self

    def set_env(self, key: str, value: str) -> "Template":
        self._env[str(key)] = str(value)
        return self

    def copy(self, host_path: str, container_path: str) -> "Template":
        """Stage ``host_path`` into the build context (requires Dockerfile / from-dockerfile path)."""
        if self._context_directory:
            raise ValueError(
                "Template.copy() cannot be used together with from_dockerfile() / with_build_context() / "
                "set_file_context_path() / Template(file_context_path=...); "
                "use a full directory context or per-file .copy(), not both."
            )
        self._copies.append((os.path.abspath(os.path.expanduser(host_path)), container_path.strip()))
        return self

    def run_cmd(self, cmd: str) -> "Template":
        """Shell command during image build (Dockerfile ``RUN`` or register ``start_cmd`` fragment)."""
        self._run_cmds.append(cmd.strip())
        return self

    def apt_install(self, packages: List[str]) -> "Template":
        """Debian/Ubuntu: ``apt-get update`` + ``apt-get install -y``."""
        pkgs = " ".join(shlex.quote(p) for p in packages if p.strip())
        if not pkgs:
            return self
        self._run_cmds.append(
            "export DEBIAN_FRONTEND=noninteractive && "
            "apt-get update && apt-get install -y --no-install-recommends " + pkgs
        )
        return self

    def pip_install(self, packages: List[str]) -> "Template":
        """``pip install`` for Python images (E2B-style helper)."""
        pkgs = " ".join(shlex.quote(p) for p in packages if p.strip())
        if not pkgs:
            return self
        return self.run_cmd(f"pip install --no-cache-dir {pkgs}")

    def npm_install(self, args: str = "install") -> "Template":
        """Run ``npm <args>`` (default ``npm install``), E2B-style helper."""
        return self.run_cmd(f"npm {args.strip()}")

    def set_start_cmd(self, cmd: str, readiness: Any = None) -> "Template":
        """
        Command run when the workload starts.

        On **this** API, for Dockerfile builds this becomes ``start_cmd`` on ``POST /templates/from-dockerfile``
        (run inside the built environment before warm snapshot). For register-only templates it is the
        registered ``start_cmd`` for the one-time warm snapshot build.

        ``readiness``: ``wait_for_port`` / ``wait_for_timeout`` / or a shell string for ``ready_cmd``.

        **Parsed** ``POST /templates/from-dockerfile`` (default on many api_server installs) runs
        ``start_cmd`` to completion *before* ``ready_cmd``. Do not set ``cmd`` to a long-running daemon
        (e.g. a web or WebSocket server): the request will block until ``run_command`` times out.
        Use ``TEMPLATE_DOCKERFILE_BUILD_MODE=docker_cli`` on the API, or leave ``start_cmd`` empty and
        rely on the Dockerfile ``CMD``/``ENTRYPOINT``.
        """
        self._start_cmd = (cmd or "").strip()
        self._start_readiness = readiness  # type: ignore[assignment]
        return self

    def set_settle_seconds(self, seconds: int) -> "Template":
        """Sleep after ``start_cmd`` before ``ready_cmd`` / snapshot (API ``settle_seconds``)."""
        self._settle_seconds = max(0, min(600, int(seconds)))
        return self

    def use_dockerfile(self, dockerfile: str) -> "Template":
        """Use explicit Dockerfile text (implies ``from-dockerfile`` API).

        For a **directory** build context (like ``docker build``), chain ``with_build_context(dir)`` **after**
        this call, or use :meth:`from_dockerfile` which sets Dockerfile + context in one step.
        """
        self._explicit_dockerfile = dockerfile
        return self

    def with_build_context(self, directory: str) -> "Template":
        """Tar this entire directory as ``context_tar_gzip_base64`` (paths relative to its root).

        Call **after** :meth:`use_dockerfile` or :meth:`from_dockerfile_file` so a Dockerfile is already set.
        If you already set context via ``Template(file_context_path=...)`` or :meth:`set_file_context_path`,
        calling this **replaces** that directory (must still follow ``use_dockerfile`` / ``from_dockerfile_file``).

        For the common case (Dockerfile + sibling files), prefer :meth:`from_dockerfile` instead.

        Mutually exclusive with :meth:`copy` (per-file ``ctx/…`` staging).
        """
        if not (self._explicit_dockerfile or "").strip():
            raise ValueError("with_build_context() requires use_dockerfile(...) or from_dockerfile_file(...) first.")
        d = os.path.abspath(os.path.expanduser(directory.strip()))
        if not os.path.isdir(d):
            raise NotADirectoryError(f"build context is not a directory: {d}")
        self._context_directory = d
        self._copies.clear()
        return self

    def from_dockerfile(self, path: str, *, context_dir: Optional[str] = None) -> "Template":
        """E2B-style: load Dockerfile from disk and use a **full directory** as build context (no ``.copy()``).

        ``context_dir`` defaults to the directory containing the Dockerfile (same as ``docker build``).
        ``COPY`` / ``ADD`` paths in the Dockerfile must be relative to that directory.

        Mutually exclusive with :meth:`copy` — calling this clears staged per-file copies.
        """
        p = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(p):
            raise FileNotFoundError(f"Dockerfile not found: {p}")
        with open(p, encoding="utf-8") as f:
            self._explicit_dockerfile = f.read()
        self._copies.clear()
        ctx = context_dir if context_dir is not None else os.path.dirname(p)
        self._context_directory = os.path.abspath(os.path.expanduser(ctx))
        if not os.path.isdir(self._context_directory):
            raise NotADirectoryError(f"context_dir is not a directory: {self._context_directory}")
        return self

    def from_dockerfile_file(self, path: str) -> "Template":
        """Load Dockerfile from disk (UTF-8). Does **not** attach a directory context unless one was
        already set via ``Template(file_context_path=...)`` / :meth:`set_file_context_path` / :meth:`from_dockerfile`.
        """
        prev_ctx = self._context_directory
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            self._explicit_dockerfile = f.read()
        self._context_directory = prev_ctx
        return self

    def set_build_arg(self, key: str, value: str) -> "Template":
        """Docker build-arg (``from-dockerfile`` only)."""
        self._build_args[str(key)] = str(value)
        return self

    def set_post_build_start_cmd(self, cmd: str, *, settle_seconds: int = 20, ready_cmd: str = "") -> "Template":
        """
        After a Dockerfile image is produced, run this in the container before commit (API fields).

        Rarely needed; prefer ``set_start_cmd`` which maps to the same API fields for from-dockerfile.
        """
        self._post_start_cmd = (cmd or "").strip()
        self._post_settle = max(0, min(600, int(settle_seconds)))
        self._post_ready_cmd = (ready_cmd or "").strip()
        return self

    # --- Build (E2B-style static API) ---

    @staticmethod
    def build(
        template: "Template",
        name: Optional[str] = None,
        *,
        alias: Optional[str] = None,
        tags: Optional[List[str]] = None,
        cpu_count: int = 2,
        memory_mb: int = 1024,
        skip_cache: bool = False,
        on_build_logs: Optional[Callable[[LogEntry], None]] = None,
        api_url: str,
        api_key: Optional[str] = None,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
        image_tag: Optional[str] = None,
        settle_seconds: Optional[int] = None,
    ) -> BuildInfo:
        """
        Register (and optionally bake) a template on your API — E2B-shaped signature.

        ``cpu_count``, ``memory_mb``, ``skip_cache``: accepted for API parity; **ignored** (no cloud builder).

        ``name``: logical ``template_id``, or ``template_id:tag`` where ``tag`` is appended to ``image_tag``
        for Dockerfile builds when ``image_tag`` is not passed explicitly.
        """
        if alias:
            warnings.warn("alias= is deprecated in E2B; pass the full name as `name`.", DeprecationWarning, stacklevel=2)
            name = name or alias
        if not name or not str(name).strip():
            raise ValueError("Template.build requires a non-empty `name` (template_id).")

        if skip_cache:
            warnings.warn("skip_cache is ignored (no E2B-style remote build cache on this API).", UserWarning, stacklevel=2)

        log_cb = on_build_logs or (lambda _e: None)
        log_cb({"level": "info", "message": "Starting template registration (local API)"})

        tid, tag_suffix = _parse_template_name(str(name).strip())
        client = APIClient(api_url, api_key, request_timeout)

        settle = int(settle_seconds) if settle_seconds is not None else template._settle_seconds
        ready_main = _ready_cmd_from_marker(template._start_readiness)

        if template._must_use_dockerfile():
            ready_final = (ready_main or template._post_ready_cmd or "").strip()
            body, _ctx = template._build_from_dockerfile_payload(
                template_id=tid,
                image_tag=image_tag or (_join_image_tag(tid, tag_suffix, tags)),
                settle_seconds=settle,
                ready_cmd=ready_final,
            )
            log_cb({"level": "info", "message": "POST /templates/from-dockerfile"})
            data = client.post(APIEndpoints.TEMPLATES_FROM_DOCKERFILE, json=body)
            log_cb({"level": "info", "message": "Template Dockerfile build finished"})
        else:
            start = _compose_start_cmd(template._run_cmds, template._start_cmd, template._post_start_cmd)
            body = {
                "template_id": tid,
                "base_image": template._base_image,
                "env": template._env,
                "start_cmd": start,
                "settle_seconds": settle,
                "ready_cmd": ready_main,
            }
            log_cb({"level": "info", "message": "POST /templates"})
            data = client.post(APIEndpoints.TEMPLATES, json=body)
            log_cb({"level": "info", "message": "Registered logical template"})

        info = BuildInfo.from_api(name=str(name).strip(), template_id=tid, data=data)
        return info

    @staticmethod
    def build_in_background(
        template: "Template",
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> BuildInfo:
        raise NotImplementedError(
            "Template.build_in_background is not supported: this API has no queued template builds "
            "or build-id status endpoint (E2B cloud only). Use Template.build(...)."
        )

    @staticmethod
    def get_build_status(
        build_info: BuildInfo,
        *,
        logs_offset: int = 0,
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError(
            "Template.get_build_status is not supported without build_in_background / remote builder."
        )

    def _must_use_dockerfile(self) -> bool:
        """True when Dockerfile materialization is required (COPY, explicit file, WORKDIR, USER)."""
        if self._explicit_dockerfile is not None:
            return True
        if self._copies:
            return True
        if self._workdir and self._workdir not in ("/", ""):
            return True
        if self._user:
            return True
        return False

    # --- Internal helpers ---

    def _build_from_dockerfile_payload(
        self,
        *,
        template_id: str,
        image_tag: Optional[str],
        settle_seconds: int,
        ready_cmd: str,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        if self._explicit_dockerfile is not None:
            dockerfile = self._explicit_dockerfile
        else:
            dockerfile = self._synthesize_dockerfile()

        if self._context_directory and self._copies:
            raise ValueError("Internal error: both directory context and per-file copies are set.")
        ctx_bytes: Optional[bytes] = None
        if self._context_directory:
            ctx_bytes = _tar_gzip_directory(self._context_directory)
        elif self._copies:
            ctx_bytes = _tar_gzip_context(self._copies)

        # Warm-snapshot phase on the API (after Dockerfile apply): extra shell before commit.
        start_after = (self._post_start_cmd or "").strip() or (self._start_cmd or "").strip()
        ready_final = (ready_cmd or "").strip()

        body: Dict[str, Any] = {
            "template_id": template_id,
            "dockerfile": dockerfile,
            "image_tag": image_tag,
            "build_args": self._build_args or None,
            "context_tar_gzip_base64": base64.b64encode(ctx_bytes).decode("ascii") if ctx_bytes else None,
            "env": self._env or None,
            "start_cmd": start_after,
            "ready_cmd": ready_final,
            "settle_seconds": int(settle_seconds),
        }
        return body, body.get("context_tar_gzip_base64")

    def _synthesize_dockerfile(self) -> str:
        lines: List[str] = [f"FROM {self._base_image}"]
        if self._env:
            for k, v in self._env.items():
                lines.append(f"ENV {k}={json.dumps(str(v))}")
        if self._workdir and self._workdir != "/":
            lines.append(f"WORKDIR {self._workdir}")
        for i, (_h, guest) in enumerate(self._copies):
            arc = f"ctx/{i}_{os.path.basename(_h)}"
            lines.append(f"COPY {arc} {guest}")
        for cmd in self._run_cmds:
            lines.append(f"RUN /bin/bash -c {shlex.quote(cmd)}")
        if self._user:
            lines.append(f"USER {self._user}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def list_registered(
        *,
        api_url: str,
        api_key: Optional[str] = None,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
    ) -> List[TemplateDefinition]:
        """``GET /templates`` — list logical templates (extension vs E2B cloud-only APIs)."""
        client = APIClient(api_url, api_key, request_timeout)
        rows = client.get(APIEndpoints.TEMPLATES)
        if not isinstance(rows, list):
            return []
        return [TemplateDefinition.from_dict(r) for r in rows]

    @staticmethod
    def get_registered(
        template_id: str,
        *,
        api_url: str,
        api_key: Optional[str] = None,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
    ) -> TemplateDefinition:
        """``GET /templates/{template_id}``."""
        client = APIClient(api_url, api_key, request_timeout)
        ep = APIEndpoints.format(APIEndpoints.TEMPLATE_GET, template_id=template_id.strip())
        data = client.get(ep)
        return TemplateDefinition.from_dict(data)


def _parse_template_name(name: str) -> Tuple[str, Optional[str]]:
    """Split ``mytpl:v1`` -> (``mytpl``, ``v1``); disallow invalid ids."""
    if ":" in name:
        tid, tag = name.rsplit(":", 1)
        tid = tid.strip()
        tag = tag.strip() or None
        if not tid:
            raise ValueError("Invalid template name: empty template_id before ':'")
        return tid, tag
    return name.strip(), None


def _join_image_tag(tid: str, tag_suffix: Optional[str], tags: Optional[List[str]]) -> Optional[str]:
    extra = list(tags or [])
    parts = [p for p in [tag_suffix, *extra] if p]
    if not parts:
        return None
    safe = "-".join(p.replace("/", "-") for p in parts)
    return f"{tid}:{safe}"


def _compose_start_cmd(run_cmds: List[str], start_cmd: str, post: str) -> str:
    parts = [c for c in run_cmds if c.strip()]
    if start_cmd:
        parts.append(start_cmd)
    if post:
        parts.append(post)
    return " && ".join(parts) if parts else ""


def _tar_gzip_context(copies: List[Tuple[str, str]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for i, (host, _guest) in enumerate(copies):
            if not os.path.exists(host):
                raise FileNotFoundError(f"copy source not found: {host}")
            arc = f"ctx/{i}_{os.path.basename(host)}"
            tf.add(host, arcname=arc, recursive=os.path.isdir(host))
    return buf.getvalue()


def _tar_gzip_directory(context_root: str) -> bytes:
    """Tar every file under ``context_root`` with **relative** arcnames (Docker ``docker build`` layout)."""
    root = os.path.abspath(os.path.expanduser(context_root))
    if not os.path.isdir(root):
        raise NotADirectoryError(f"build context is not a directory: {root}")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                abs_path = os.path.join(dirpath, name)
                if not os.path.isfile(abs_path):
                    continue
                rel = os.path.relpath(abs_path, root)
                arc = rel.replace(os.sep, "/")
                tf.add(abs_path, arcname=arc, recursive=False)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Async façade (same semantics; runs sync client in asyncio executor)
# ---------------------------------------------------------------------------


class AsyncTemplate:
    """Async wrapper matching E2B's async template entrypoints where applicable."""

    @staticmethod
    async def build(template: Template, name: Optional[str] = None, **kwargs: Any) -> BuildInfo:
        import asyncio

        return await asyncio.to_thread(Template.build, template, name, **kwargs)

    @staticmethod
    async def build_in_background(template: Template, name: Optional[str] = None, **kwargs: Any) -> BuildInfo:
        import asyncio

        return await asyncio.to_thread(Template.build_in_background, template, name, **kwargs)

    @staticmethod
    async def get_build_status(build_info: BuildInfo, **kwargs: Any) -> Any:
        import asyncio

        return await asyncio.to_thread(Template.get_build_status, build_info, **kwargs)

    @staticmethod
    async def list_registered(**kwargs: Any) -> List[TemplateDefinition]:
        import asyncio

        return await asyncio.to_thread(Template.list_registered, **kwargs)

    @staticmethod
    async def get_registered(template_id: str, **kwargs: Any) -> TemplateDefinition:
        import asyncio

        return await asyncio.to_thread(Template.get_registered, template_id, **kwargs)
