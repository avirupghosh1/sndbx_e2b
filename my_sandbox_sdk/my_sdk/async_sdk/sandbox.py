"""
Asynchronous sandbox implementation for My Sandbox SDK.
"""

from typing import Optional, Dict, Any, List

from ..api.async_client import AsyncAPIClient, APIEndpoints
from ..config import DEFAULT_SDK_REQUEST_TIMEOUT
from ..models import (
    SandboxInfo,
    SandboxState,
    SandboxLifecycle,
    SnapshotRecord,
    CommandResult,
    ProcessInfo,
    SandboxMetrics,
)
from ..exceptions import SandboxNotFoundException, SandboxException
from .commands import AsyncCommands
from .filesystem import AsyncFilesystem


class AsyncSandbox:
    """Asynchronous sandbox client."""
    
    def __init__(
        self,
        sandbox_id: str,
        api_url: str,
        api_key: Optional[str] = None,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
    ):
        """
        Initialize asynchronous sandbox.
        
        Args:
            sandbox_id: ID of the sandbox
            api_url: API server URL
            api_key: Optional API key
            request_timeout: Request timeout in seconds
        """
        self.sandbox_id = sandbox_id
        self.api_url = api_url
        self.api_key = api_key
        self.request_timeout = request_timeout
        
        self._api = AsyncAPIClient(api_url, api_key, request_timeout)
        self._commands = AsyncCommands(self.sandbox_id, self._api)
        self._filesystem = AsyncFilesystem(self.sandbox_id, self._api)
    
    @classmethod
    async def create(
        cls,
        api_url: str,
        api_key: Optional[str] = None,
        template_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        from_snapshot_image: Optional[str] = None,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
    ) -> "AsyncSandbox":
        """
        Create a new sandbox asynchronously.
        
        Args:
            api_url: API server URL
            api_key: Optional API key
            template_id: Optional template ID to use for sandbox
            metadata: Optional metadata to attach to sandbox
            request_timeout: Request timeout in seconds
            
        Returns:
            Newly created AsyncSandbox instance
            
        Example:
            ```python
            sandbox = await AsyncSandbox.create(api_url="http://localhost:8000")
            ```
        """
        api_client = AsyncAPIClient(api_url, api_key, request_timeout)
        
        body = {}
        if template_id:
            body["template_id"] = template_id
        if metadata:
            body["metadata"] = metadata
        if from_snapshot_image:
            body["from_snapshot_image"] = from_snapshot_image
        
        response = await api_client.post(
            APIEndpoints.SANDBOX_CREATE,
            json=body,
        )
        
        sandbox_id = response.get("sandbox_id")
        if not sandbox_id:
            raise SandboxException("Failed to create sandbox: no ID in response")
        
        return cls(
            sandbox_id=sandbox_id,
            api_url=api_url,
            api_key=api_key,
            request_timeout=request_timeout,
        )

    @classmethod
    def connect(
        cls,
        sandbox_id: str,
        api_url: str,
        api_key: Optional[str] = None,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
    ) -> "AsyncSandbox":
        """Attach to an existing sandbox (no ``POST /sandboxes``)."""
        return cls(
            sandbox_id=sandbox_id,
            api_url=api_url,
            api_key=api_key,
            request_timeout=request_timeout,
        )
    
    @property
    def commands(self) -> AsyncCommands:
        """Access sandbox commands module."""
        return self._commands
    
    @property
    def files(self) -> AsyncFilesystem:
        """Access sandbox filesystem module."""
        return self._filesystem
    
    async def info(self) -> SandboxInfo:
        """
        Get sandbox information.
        
        Returns:
            SandboxInfo with current sandbox status
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX,
            sandbox_id=self.sandbox_id,
        )
        response = await self._api.get(endpoint)
        return SandboxInfo.from_dict(response)

    async def lifecycle(self) -> SandboxLifecycle:
        """Cheap liveness: DB state + whether the workload is still running."""
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_STATUS,
            sandbox_id=self.sandbox_id,
        )
        response = await self._api.get(endpoint)
        return SandboxLifecycle.from_dict(response)

    async def create_snapshot(self, label: Optional[str] = None) -> SnapshotRecord:
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_SNAPSHOT,
            sandbox_id=self.sandbox_id,
        )
        body: Dict[str, Any] = {}
        if label:
            body["label"] = label
        raw = await self._api.post(endpoint, json=body)
        return SnapshotRecord.from_dict(raw)

    async def list_snapshots(self, limit: int = 50) -> List[SnapshotRecord]:
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_SNAPSHOTS_LIST,
            sandbox_id=self.sandbox_id,
        )
        raw = await self._api.get(endpoint, params={"limit": limit})
        if not isinstance(raw, list):
            return []
        return [SnapshotRecord.from_dict(x) for x in raw if isinstance(x, dict)]
    
    async def is_running(self) -> bool:
        """
        Check if sandbox is running.
        
        Returns:
            True if sandbox is running, False otherwise
        """
        try:
            info = await self.info()
            return info.state == SandboxState.RUNNING
        except SandboxNotFoundException:
            return False
    
    async def kill(self, request_timeout: Optional[float] = None) -> bool:
        """
        Kill the sandbox asynchronously.
        
        Args:
            request_timeout: Optional timeout override for this request
            
        Returns:
            True if sandbox was killed, False otherwise
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_KILL,
            sandbox_id=self.sandbox_id,
        )
        
        api = AsyncAPIClient(
            self.api_url,
            self.api_key,
            request_timeout or self.request_timeout,
        )
        
        try:
            await api.post(endpoint)
            return True
        except SandboxNotFoundException:
            return False
    
    async def pause(self) -> bool:
        """
        Pause the sandbox asynchronously.
        
        Returns:
            True if paused successfully
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_PAUSE,
            sandbox_id=self.sandbox_id,
        )
        await self._api.post(endpoint)
        return True
    
    async def resume(self) -> bool:
        """
        Resume the paused sandbox asynchronously.
        
        Returns:
            True if resumed successfully
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_RESUME,
            sandbox_id=self.sandbox_id,
        )
        await self._api.post(endpoint)
        return True
    
    async def metrics(self) -> SandboxMetrics:
        """
        Get sandbox metrics (CPU, memory, disk usage) asynchronously.
        
        Returns:
            SandboxMetrics with current resource usage
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_METRICS,
            sandbox_id=self.sandbox_id,
        )
        response = await self._api.get(endpoint)
        return SandboxMetrics.from_dict(response)

    async def spawn_agent(
        self,
        agent_name: str,
        agent_code: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        auto_start: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Spawn an agent whose *code* runs inside this sandbox (API uploads ``agent_code`` and execs it there).

        Use ``config["single_run"]: True`` so the API runs ``python3`` once per spawn instead of every second.
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.AGENTS_SPAWN,
            sandbox_id=self.sandbox_id,
        )
        body: Dict[str, Any] = {
            "agent_name": agent_name,
            "agent_code": agent_code,
            "config": dict(config or {}),
        }
        if auto_start is not None:
            body["auto_start"] = auto_start
        return await self._api.post(endpoint, json=body)

    async def list_agents(self) -> Dict[str, Any]:
        """List agents attached to this sandbox."""
        endpoint = APIEndpoints.format(
            APIEndpoints.AGENTS_LIST,
            sandbox_id=self.sandbox_id,
        )
        return await self._api.get(endpoint)

    async def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """Get one agent's status."""
        endpoint = APIEndpoints.format(
            APIEndpoints.AGENT_GET,
            sandbox_id=self.sandbox_id,
            agent_id=agent_id,
        )
        return await self._api.get(endpoint)

    async def kill_agent(self, agent_id: str, force: bool = False) -> Dict[str, Any]:
        """Stop the agent worker thread on the API (in-sandbox process already exited if ``single_run``)."""
        endpoint = APIEndpoints.format(
            APIEndpoints.AGENT_KILL,
            sandbox_id=self.sandbox_id,
            agent_id=agent_id,
        )
        return await self._api.post(endpoint, json={"agent_id": agent_id, "force": force})

    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - kills sandbox on exit."""
        try:
            await self.kill()
        except Exception:
            pass
    
    def __repr__(self) -> str:
        """String representation."""
        return f"AsyncSandbox(id={self.sandbox_id}, url={self.api_url})"
