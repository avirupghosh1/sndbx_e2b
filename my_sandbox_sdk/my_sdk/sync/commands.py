"""
Synchronous commands module for My Sandbox SDK.
"""

from typing import Optional, List, Dict, Any, Iterator
import uuid
from urllib.parse import urljoin

from ..api import APIEndpoints
from ..models import CommandResult, ProcessInfo
from ..exceptions import CommandException


class Commands:
    """Synchronous module for executing commands in sandbox."""
    
    def __init__(self, sandbox_id: str, api_client):
        """
        Initialize commands module.
        
        Args:
            sandbox_id: ID of the sandbox
            api_client: API client instance
        """
        self.sandbox_id = sandbox_id
        self._api = api_client
    
    def run(
        self,
        command: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        envs: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        user: Optional[str] = None,
        **kwargs: Any,
    ) -> CommandResult:
        """
        Run a command in the sandbox.
        
        Args:
            command: Command string to execute
            cwd: Working directory for the command
            env: Environment variables to set
            envs: Alias for ``env`` (E2B-shaped callers).
            timeout: Timeout for command execution in seconds
            user: Optional user to run as
            **kwargs: Ignored (shim compatibility).
        """
        _ = kwargs
        endpoint = APIEndpoints.format(
            APIEndpoints.COMMANDS_RUN,
            sandbox_id=self.sandbox_id,
        )
        
        body: Dict[str, Any] = {"command": command}
        if cwd:
            body["cwd"] = cwd
        merged: Dict[str, str] = {}
        if env:
            merged.update(env)
        if envs:
            merged.update(envs)
        if merged:
            body["env"] = merged
        if timeout:
            body["timeout"] = timeout
        if user is not None:
            body["user"] = user
        
        response = self._api.post(endpoint, json=body)
        return CommandResult.from_dict(response)

    def run_stream(
        self,
        command: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        user: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """
        Run a command and stream JSON events from the API (Server-Sent Events).

        Yields dicts with ``type`` of ``stdout``, ``stderr``, ``error``, or ``exit``
        (final event includes ``exit_code``). The server streams chunks as the container emits them.

        Example:
            ```python
            buf = []
            for ev in sandbox.commands.run_stream("for i in 1 2 3; do echo $i; sleep 1; done"):
                if ev.get("type") == "stdout":
                    buf.append(ev.get("chunk", ""))
                elif ev.get("type") == "exit":
                    print(ev["exit_code"], "".join(buf))
            ```
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.COMMANDS_RUN_STREAM,
            sandbox_id=self.sandbox_id,
        )
        body: Dict[str, Any] = {"command": command}
        if cwd is not None:
            body["cwd"] = cwd
        if env:
            body["env"] = env
        if timeout is not None:
            body["timeout"] = timeout
        if user is not None:
            body["user"] = user
        yield from self._api.iter_post_sse(endpoint, body)

    def run_python(
        self,
        code: str,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> CommandResult:
        """
        Run a Python source string inside the sandbox (E2B-style code cell).

        Writes a temporary ``.py`` file via the files API, executes ``python3`` on it,
        then deletes the temp file. For arbitrary shell, use :meth:`run` instead.

        Args:
            code: Python source to execute as a script (``if __name__ == '__main__'`` not required).
            cwd: Working directory for the interpreter process.
            timeout: Max seconds for the run (server-enforced).

        Returns:
            CommandResult with stdout/stderr from ``python3``.
        """
        cell = f"/tmp/sdk_cell_{uuid.uuid4().hex[:12]}.py"
        write_ep = APIEndpoints.format(APIEndpoints.FILES_WRITE, sandbox_id=self.sandbox_id)
        self._api.post(write_ep, json={"path": cell, "content": code})
        try:
            return self.run(f"python3 {cell}", cwd=cwd, timeout=timeout)
        finally:
            del_ep = APIEndpoints.format(APIEndpoints.FILES_DELETE, sandbox_id=self.sandbox_id)
            try:
                self._api.post(del_ep, json={"path": cell, "recursive": False})
            except Exception:
                pass

    def list(self) -> List[ProcessInfo]:
        """
        List all running processes in the sandbox.
        
        Returns:
            List of ProcessInfo for all running processes
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.COMMANDS_LIST,
            sandbox_id=self.sandbox_id,
        )
        
        response = self._api.get(endpoint)
        processes = response.get("processes", [])
        return [ProcessInfo.from_dict(p) for p in processes]
    
    def kill(self, pid: int) -> bool:
        """
        Kill a running process by PID.
        
        Args:
            pid: Process ID to kill
            
        Returns:
            True if process was killed
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.COMMANDS_KILL,
            sandbox_id=self.sandbox_id,
            pid=pid,
        )
        
        try:
            self._api.post(endpoint)
            return True
        except Exception:
            return False
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        pass
