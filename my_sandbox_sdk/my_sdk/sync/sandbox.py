"""
Synchronous sandbox implementation for My Sandbox SDK.
"""

from typing import Optional, Dict, Any, List
from urllib.parse import urljoin

from ..api.sync import APIClient, APIEndpoints
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
from .commands import Commands
from .filesystem import Filesystem


class Sandbox:
    """Synchronous sandbox client."""
    
    def __init__(
        self,
        sandbox_id: str,
        api_url: str,
        api_key: Optional[str] = None,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
    ):
        """
        Initialize sandbox.
        
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
        
        self._api = APIClient(api_url, api_key, request_timeout)
        self._commands = Commands(self.sandbox_id, self._api)
        self._filesystem = Filesystem(self.sandbox_id, self._api)
    
    @classmethod
    def create(
        cls,
        api_url: str,
        api_key: Optional[str] = None,
        template_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        from_snapshot_image: Optional[str] = None,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
    ) -> "Sandbox":
        """
        Create a new sandbox.
        
        Args:
            api_url: API server URL
            api_key: Optional API key
            template_id: Optional template ID to use for sandbox
            metadata: Optional metadata to attach to sandbox
            request_timeout: Request timeout in seconds
            
        Returns:
            Newly created Sandbox instance
            
        Example:
            ```python
            sandbox = Sandbox.create(api_url="http://localhost:8000")
            ```
        """
        api_client = APIClient(api_url, api_key, request_timeout)
        
        body = {}
        if template_id:
            body["template_id"] = template_id
        if metadata:
            body["metadata"] = metadata
        if from_snapshot_image:
            body["from_snapshot_image"] = from_snapshot_image
        
        response = api_client.post(
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
    ) -> "Sandbox":
        """Attach to an existing sandbox (no ``POST /sandboxes``). Same as ``Sandbox(...)``."""
        return cls(
            sandbox_id=sandbox_id,
            api_url=api_url,
            api_key=api_key,
            request_timeout=request_timeout,
        )

    @property
    def commands(self) -> Commands:
        """Access sandbox commands module."""
        return self._commands
    
    @property
    def files(self) -> Filesystem:
        """Access sandbox filesystem module."""
        return self._filesystem
    
    def info(self) -> SandboxInfo:
        """
        Get sandbox information.
        
        Returns:
            SandboxInfo with current sandbox status
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX,
            sandbox_id=self.sandbox_id,
        )
        response = self._api.get(endpoint)
        return SandboxInfo.from_dict(response)

    def lifecycle(self) -> SandboxLifecycle:
        """Cheap liveness: DB state + whether the workload is still running."""
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_STATUS,
            sandbox_id=self.sandbox_id,
        )
        response = self._api.get(endpoint)
        return SandboxLifecycle.from_dict(response)

    def create_snapshot(self, label: Optional[str] = None) -> SnapshotRecord:
        """Docker only: ``docker commit`` this sandbox's filesystem to a new local image."""
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_SNAPSHOT,
            sandbox_id=self.sandbox_id,
        )
        body: Dict[str, Any] = {}
        if label:
            body["label"] = label
        raw = self._api.post(endpoint, json=body)
        return SnapshotRecord.from_dict(raw)

    def list_snapshots(self, limit: int = 50) -> List[SnapshotRecord]:
        """List snapshot records for this sandbox."""
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_SNAPSHOTS_LIST,
            sandbox_id=self.sandbox_id,
        )
        raw = self._api.get(endpoint, params={"limit": limit})
        if not isinstance(raw, list):
            return []
        return [SnapshotRecord.from_dict(x) for x in raw if isinstance(x, dict)]
    
    def is_running(self) -> bool:
        """
        Check if sandbox is running.
        
        Returns:
            True if sandbox is running, False otherwise
        """
        try:
            info = self.info()
            return info.state == SandboxState.RUNNING
        except SandboxNotFoundException:
            return False
    
    def kill(self, request_timeout: Optional[float] = None) -> bool:
        """
        Kill the sandbox.
        
        Args:
            request_timeout: Optional timeout override for this request
            
        Returns:
            True if sandbox was killed, False otherwise
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_KILL,
            sandbox_id=self.sandbox_id,
        )
        
        api = APIClient(
            self.api_url,
            self.api_key,
            request_timeout or self.request_timeout,
        )
        
        try:
            api.post(endpoint)
            return True
        except SandboxNotFoundException:
            return False
    
    def pause(self) -> bool:
        """
        Pause the sandbox.
        
        Returns:
            True if paused successfully
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_PAUSE,
            sandbox_id=self.sandbox_id,
        )
        self._api.post(endpoint)
        return True
    
    def resume(self) -> bool:
        """
        Resume the paused sandbox.
        
        Returns:
            True if resumed successfully
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_RESUME,
            sandbox_id=self.sandbox_id,
        )
        self._api.post(endpoint)
        return True
    
    def metrics(self) -> SandboxMetrics:
        """
        Get sandbox metrics (CPU, memory, disk usage).
        
        Returns:
            SandboxMetrics with current resource usage
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_METRICS,
            sandbox_id=self.sandbox_id,
        )
        response = self._api.get(endpoint)
        return SandboxMetrics.from_dict(response)

    def spawn_agent(
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
        return self._api.post(endpoint, json=body)

    def list_agents(self) -> Dict[str, Any]:
        """List agents attached to this sandbox."""
        endpoint = APIEndpoints.format(
            APIEndpoints.AGENTS_LIST,
            sandbox_id=self.sandbox_id,
        )
        return self._api.get(endpoint)

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """Get one agent's status."""
        endpoint = APIEndpoints.format(
            APIEndpoints.AGENT_GET,
            sandbox_id=self.sandbox_id,
            agent_id=agent_id,
        )
        return self._api.get(endpoint)

    def kill_agent(self, agent_id: str, force: bool = False) -> Dict[str, Any]:
        """Stop the agent worker thread on the API (in-sandbox process already exited if ``single_run``)."""
        endpoint = APIEndpoints.format(
            APIEndpoints.AGENT_KILL,
            sandbox_id=self.sandbox_id,
            agent_id=agent_id,
        )
        return self._api.post(endpoint, json={"agent_id": agent_id, "force": force})

    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - kills sandbox on exit."""
        try:
            self.kill()
        except Exception:
            pass
    
    def __repr__(self) -> str:
        """String representation."""
        return f"Sandbox(id={self.sandbox_id}, url={self.api_url})"
