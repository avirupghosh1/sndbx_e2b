"""
Asynchronous commands module for My Sandbox SDK.
"""

from typing import Optional, List, Dict, Any, AsyncIterator
from functools import partial
import asyncio
import uuid

from ..api import APIEndpoints
from ..models import CommandResult, ProcessInfo
from ..exceptions import CommandException


class AsyncCommands:
    """Asynchronous module for executing commands in sandbox."""
    
    def __init__(self, sandbox_id: str, api_client):
        """
        Initialize async commands module.
        
        Args:
            sandbox_id: ID of the sandbox
            api_client: Async API client instance
        """
        self.sandbox_id = sandbox_id
        self._api = api_client
    
    async def run(
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
        Run a command in the sandbox asynchronously.
        
        Args:
            command: Command string to execute
            cwd: Working directory for the command
            env: Environment variables to set
            envs: Alias for ``env`` (E2B / Custodian-shaped callers may pass ``envs=``).
            timeout: Timeout for command execution in seconds
            user: Optional user to run as (API forwards to the workload)
            **kwargs: Ignored (forward-compatibility with shim-shaped call sites).
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
        
        response = await self._api.post(endpoint, json=body)
        return CommandResult.from_dict(response)

    async def run_stream(
        self,
        command: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        user: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Async variant of :meth:`Commands.run_stream` (reads SSE lines via a thread pool)."""
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
        loop = asyncio.get_event_loop()
        it = self._api.iter_post_sse(endpoint, body)
        _SENT = object()

        while True:
            ev = await loop.run_in_executor(None, partial(next, it, _SENT))
            if ev is _SENT:
                break
            yield ev

    async def run_python(
        self,
        code: str,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> CommandResult:
        """Run Python source in the sandbox (see sync :meth:`Commands.run_python`)."""
        cell = f"/tmp/sdk_cell_{uuid.uuid4().hex[:12]}.py"
        write_ep = APIEndpoints.format(APIEndpoints.FILES_WRITE, sandbox_id=self.sandbox_id)
        await self._api.post(write_ep, json={"path": cell, "content": code})
        try:
            return await self.run(f"python3 {cell}", cwd=cwd, timeout=timeout)
        finally:
            del_ep = APIEndpoints.format(APIEndpoints.FILES_DELETE, sandbox_id=self.sandbox_id)
            try:
                await self._api.post(del_ep, json={"path": cell, "recursive": False})
            except Exception:
                pass

    async def list(self) -> List[ProcessInfo]:
        """
        List all running processes in the sandbox asynchronously.
        
        Returns:
            List of ProcessInfo for all running processes
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.COMMANDS_LIST,
            sandbox_id=self.sandbox_id,
        )
        
        response = await self._api.get(endpoint)
        processes = response.get("processes", [])
        return [ProcessInfo.from_dict(p) for p in processes]
    
    async def kill(self, pid: int) -> bool:
        """
        Kill a running process by PID asynchronously.
        
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
            await self._api.post(endpoint)
            return True
        except Exception:
            return False
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        pass
