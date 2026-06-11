"""
LangChain **Deep Agents** sandbox backend for ``my_sdk`` sandboxes.

Mirrors the pattern of ``langchain_modal.ModalSandbox``: create a sandbox with this SDK,
wrap it, pass ``backend=...`` to ``deepagents.create_deep_agent``.

Install::

    pip install "my-sandbox-sdk[deepagents]"   # pulls deepagents + langchain-openai
    # or: pip install deepagents langchain-openai

For the **LLM**, use any LangChain chat model (e.g. ``langchain_openai.ChatOpenAI`` with
``openai_api_base=https://openrouter.ai/api/v1``, or local Ollama via ``openai_api_base=http://127.0.0.1:11434/v1``
as in ``examples/deepagents_my_sandbox.py`` with ``USE_OLLAMA=1``). Deep Agents
only needs a ``BaseChatModel``; the sandbox is wired via ``SandboxDeepAgentBackend``.

Usage::

    from my_sdk.sync.sandbox import Sandbox
    from my_sdk.integrations.deepagents_backend import SandboxDeepAgentBackend
    from deepagents import create_deep_agent

    sb = Sandbox.create(api_url="http://localhost:8000", api_key="...")
    backend = SandboxDeepAgentBackend(sandbox=sb)
    agent = create_deep_agent(model=..., backend=backend, ...)
    try:
        agent.invoke({"messages": [...]})
    finally:
        sb.kill()

**Parallel ``write_file`` + ``execute``:** LangGraph's agent runs each tool call from one
assistant turn as a **separate concurrent task**. ``parallel_tool_calls=False`` on the chat
model does not serialize those runs. :meth:`execute` therefore waits (polls) briefly for
absolute ``*.py`` script paths referenced as ``python3 /path/file.py`` if they are not on disk
yet, so a batched write + run usually succeeds. Disable with ``execute_file_race_wait_sec=0``.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

import shlex

try:
    from deepagents.backends.protocol import (
        ExecuteResponse,
        FileDownloadResponse,
        FileUploadResponse,
        WriteResult,
    )
    from deepagents.backends.sandbox import BaseSandbox
except ImportError as e:  # pragma: no cover - import guard
    raise ImportError(
        "The Deep Agents integration requires the `deepagents` package. "
        'Install with: pip install "deepagents>=0.6"'
    ) from e

from my_sdk.exceptions import FileNotFoundException

if TYPE_CHECKING:
    from my_sdk.sync.sandbox import Sandbox


logger = logging.getLogger(__name__)


# Deep Agents combines stdout/stderr for the model; cap size to avoid huge states.
_MAX_COMBINED_OUTPUT_CHARS = 120_000

# LangGraph's create_agent dispatches each tool_call as its own Send → tools can run **concurrently**.
# Models often still return write_file + execute in one AIMessage even when parallel_tool_calls=False
# (that flag is only a provider hint). Briefly wait so execute does not win the race ahead of write.
_EXECUTE_RACE_WAIT_SEC = 12.0
_EXECUTE_RACE_POLL_SEC = 0.05
_PY_SCRIPT_PATH = re.compile(r"\bpython3?\s+(/\S+\.py)\b")


def _python_script_paths(command: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for m in _PY_SCRIPT_PATH.finditer(command):
        p = m.group(1)
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


class SandboxDeepAgentBackend(BaseSandbox):
    """Bridge ``my_sdk.sync.sandbox.Sandbox`` to Deep Agents ``BaseSandbox``."""

    def __init__(
        self,
        sandbox: "Sandbox",
        *,
        default_exec_timeout_sec: float = 120.0,
        execute_file_race_wait_sec: float | None = None,
    ):
        self._sandbox = sandbox
        self._default_exec_timeout = default_exec_timeout_sec
        # None → use module default; 0.0 disables wait-for-file (strict / tests).
        self._execute_race_wait_sec = (
            execute_file_race_wait_sec
            if execute_file_race_wait_sec is not None
            else _EXECUTE_RACE_WAIT_SEC
        )

    @property
    def id(self) -> str:
        return self._sandbox.sandbox_id

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        to = float(timeout) if timeout is not None else float(self._default_exec_timeout)
        self._wait_for_python_targets_if_missing(command, to)
        r = self._sandbox.commands.run(command, cwd="/", timeout=to)
        parts = []
        if r.stdout:
            parts.append(r.stdout)
        if r.stderr:
            parts.append(r.stderr)
        out = "\n".join(parts) if parts else ""
        truncated = len(out) > _MAX_COMBINED_OUTPUT_CHARS
        if truncated:
            out = out[:_MAX_COMBINED_OUTPUT_CHARS]
        return ExecuteResponse(
            output=out,
            exit_code=r.exit_code,
            truncated=truncated,
        )

    def _paths_exist_in_sandbox(self, paths: list[str], run_timeout: float) -> bool:
        if not paths:
            return True
        checks = " && ".join(f"test -f {shlex.quote(p)}" for p in paths)
        chk = self._sandbox.commands.run(checks, cwd="/", timeout=run_timeout)
        return chk.exit_code == 0

    def _wait_for_python_targets_if_missing(self, command: str, exec_timeout: float) -> None:
        wait_budget = float(self._execute_race_wait_sec)
        if wait_budget <= 0:
            return
        paths = _python_script_paths(command)
        if not paths:
            return
        quick = min(5.0, max(1.0, exec_timeout * 0.1))
        if self._paths_exist_in_sandbox(paths, quick):
            return
        deadline = time.monotonic() + min(wait_budget, max(2.0, exec_timeout * 0.25))
        logger.info(
            "execute: script path(s) not yet present %s — polling until ready (LangGraph "
            "may run write_file and execute in parallel); deadline in %.1fs",
            paths,
            deadline - time.monotonic(),
        )
        while time.monotonic() < deadline:
            time.sleep(_EXECUTE_RACE_POLL_SEC)
            if self._paths_exist_in_sandbox(paths, quick):
                logger.info("execute: path(s) now present, running command: %s", paths)
                return
        logger.warning(
            "execute: timed out waiting for path(s) %s — running command anyway",
            paths,
        )

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        try:
            self._sandbox.files.write(file_path, content)

            return WriteResult(
                error=None,
                path=file_path,
                files_update=[
                    {
                        "path": file_path,
                        "content": content,
                    }
                ],
            )

        except Exception as e:
            return WriteResult(
                error=str(e),
                path=file_path,
                files_update=[]
            )



    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Write each file via the REST ``files/write`` API (Docker: in-container Python + verify).

        On success, Deep Agents only needs ``error=None``. If the API returns OK but the file is
        not visible from ``exec`` (same container Docker uses for commands), we surface
        ``write_verify_failed`` so the agent does not assume the path exists.
        """
        results: list[FileUploadResponse] = []
        for path, data in files:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                results.append(
                    FileUploadResponse(
                        path=path,
                        error="invalid_path",
                    )
                )
                logger.warning(
                    "upload_files: non-UTF-8 bytes skipped for %r (use text files or extend backend)",
                    path,
                )
                continue
            try:
                self._sandbox.files.write(path, text)
                # Same container the API uses for ``commands/run``: confirm the file exists on disk.
                q = shlex.quote(path)
                chk = self._sandbox.commands.run(
                    f"test -f {q} && ls -l {q}",
                    cwd="/",
                    timeout=min(15.0, float(self._default_exec_timeout)),
                )
                if chk.exit_code == 0:
                    logger.info(
                        "upload_files: write OK and file visible in sandbox sandbox_id=%s path=%r ls=%r",
                        self._sandbox.sandbox_id,
                        path,
                        (chk.stdout or "").strip()[:500],
                    )
                    results.append(FileUploadResponse(path=path, error=None))
                else:
                    detail = (
                        f"exit={chk.exit_code} "
                        f"stdout={(chk.stdout or '')[:400]!r} "
                        f"stderr={(chk.stderr or '')[:400]!r}"
                    )
                    logger.warning(
                        "upload_files: API write returned but test -f failed sandbox_id=%s path=%r %s",
                        self._sandbox.sandbox_id,
                        path,
                        detail,
                    )
                    results.append(
                        FileUploadResponse(
                            path=path,
                            error=f"write_verify_failed: {detail}",
                        )
                    )
            except Exception as e:
                logger.exception("upload_files failed for %s", path)
                results.append(FileUploadResponse(path=path, error=str(e)))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results: list[FileDownloadResponse] = []
        for path in paths:
            try:
                text = self._sandbox.files.read(path)
            except FileNotFoundException:
                results.append(
                    FileDownloadResponse(path=path, content=None, error="file_not_found")
                )
            except Exception as e:
                results.append(FileDownloadResponse(path=path, content=None, error=str(e)))
            else:
                results.append(
                    FileDownloadResponse(
                        path=path,
                        content=text.encode("utf-8"),
                        error=None,
                    )
                )
        return results
