"""
Asynchronous sandbox implementation for My Sandbox SDK.
"""

import os
from typing import Optional, Dict, Any, List

from ..api.async_client import AsyncAPIClient, APIEndpoints
from ..config import DEFAULT_SDK_REQUEST_TIMEOUT
from ..models import (
    SandboxInfo,
    SandboxState,
    SandboxLifecycle,
    E2bConnectionInfo,
    SnapshotRecord,
    CommandResult,
    ProcessInfo,
    SandboxMetrics,
)
from ..exceptions import APIException, SandboxNotFoundException, SandboxException
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
        self._e2b: Optional[E2bConnectionInfo] = None

    @staticmethod
    def _resolve_api_url(api_url: Optional[str]) -> str:
        raw = (api_url or os.environ.get("SANDBOX_API_URL") or os.environ.get("E2B_API_URL") or "").strip()
        if not raw:
            raise SandboxException(
                "api_url is required (pass api_url=... or set SANDBOX_API_URL / E2B_API_URL)"
            )
        return raw.rstrip("/")

    @classmethod
    async def create(
        cls,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        template_id: Optional[str] = None,
        template: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        from_snapshot_image: Optional[str] = None,
        timeout: Optional[int] = None,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
        **kwargs: Any,
    ) -> "AsyncSandbox":
        """
        Create a new sandbox asynchronously.

        After create, mints E2B drop-in fields via ``GET …/e2b-connection`` (same as ``e2b`` shim).

        Unknown keyword arguments (e.g. ``network=`` from shim-shaped callers) are ignored.
        """
        kwargs.pop("network", None)
        kwargs.pop("auto_pause", None)
        _ = kwargs  # tolerate extra shim kwargs

        resolved = cls._resolve_api_url(api_url)
        api_client = AsyncAPIClient(resolved, api_key, request_timeout)

        body: Dict[str, Any] = {}
        tid = template_id or template
        if tid:
            body["template_id"] = tid
        if metadata:
            body["metadata"] = metadata
        if from_snapshot_image:
            body["from_snapshot_image"] = from_snapshot_image
        if timeout is not None:
            body["timeout"] = int(timeout)

        response = await api_client.post(
            APIEndpoints.SANDBOX_CREATE,
            json=body,
        )

        sandbox_id = response.get("sandbox_id")
        if not sandbox_id:
            raise SandboxException("Failed to create sandbox: no ID in response")

        inst = cls(
            sandbox_id=sandbox_id,
            api_url=resolved,
            api_key=api_key,
            request_timeout=request_timeout,
        )
        await inst.refresh_e2b_connection()
        return inst

    @classmethod
    async def beta_create(
        cls,
        *,
        template: Optional[str] = None,
        template_id: Optional[str] = None,
        timeout: int = 3600,
        auto_pause: bool = True,
        envs: Optional[Dict[str, str]] = None,
        network: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        **kwargs: Any,
    ) -> "AsyncSandbox":
        """Custodian / shim-shaped entrypoint (maps ``envs`` into metadata for the API)."""
        del auto_pause, network, kwargs
        meta: Dict[str, Any] = {}
        if envs:
            meta["e2b_shim_envs"] = dict(envs)
        tid = template_id or template or "python:3.11"
        return await cls.create(
            api_url=api_url,
            api_key=api_key,
            template_id=tid.strip(),
            metadata=meta or None,
            timeout=int(timeout),
        )

    @classmethod
    def attach(
        cls,
        sandbox_id: str,
        api_url: str,
        api_key: Optional[str] = None,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
    ) -> "AsyncSandbox":
        """Attach without calling ``GET …/e2b-connection`` (REST-only handle)."""
        return cls(
            sandbox_id=sandbox_id,
            api_url=api_url.rstrip("/"),
            api_key=api_key,
            request_timeout=request_timeout,
        )

    @classmethod
    async def connect(
        cls,
        sandbox_id: str,
        *,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 3600,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
        **kwargs: Any,
    ) -> "AsyncSandbox":
        """
        Reattach to a running sandbox: ``GET …/status`` then ``GET …/e2b-connection``.

        ``api_url`` defaults from ``SANDBOX_API_URL`` / ``E2B_API_URL``. Extra kwargs are ignored
        (shim compatibility).
        """
        del timeout, kwargs
        resolved = cls._resolve_api_url(api_url)
        inst = cls(
            sandbox_id=sandbox_id,
            api_url=resolved,
            api_key=api_key,
            request_timeout=request_timeout,
        )
        life = await inst.lifecycle()
        if not life.running:
            raise SandboxException(f"connect: sandbox {sandbox_id} is not running")
        await inst.refresh_e2b_connection()
        return inst
    
    @property
    def commands(self) -> AsyncCommands:
        """Access sandbox commands module."""
        return self._commands
    
    @property
    def files(self) -> AsyncFilesystem:
        """Access sandbox filesystem module."""
        return self._filesystem

    def _require_e2b(self) -> E2bConnectionInfo:
        if self._e2b is None:
            raise RuntimeError(
                "E2B drop-in connection not loaded. Use create()/connect(), or "
                "``await refresh_e2b_connection()``."
            )
        return self._e2b

    @property
    def e2b_connection(self) -> E2bConnectionInfo:
        """Minted ``GET …/e2b-connection`` payload (WebSocket URL + traffic token)."""
        return self._require_e2b()

    @property
    def ws_url(self) -> str:
        return self._require_e2b().ws_url

    @property
    def traffic_access_token(self) -> str:
        return self._require_e2b().traffic_access_token

    @property
    def e2b_style_host(self) -> str:
        return self._require_e2b().e2b_style_host

    def get_host(self, _port: int = 8765) -> str:
        """Return authority + path (no scheme) for ``wss://{{get_host(port)}}`` (E2B-shaped)."""
        return self._require_e2b().e2b_style_host

    async def refresh_e2b_connection(self) -> E2bConnectionInfo:
        """Fetch and cache ``GET /sandboxes/{{id}}/e2b-connection``."""
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_E2B_CONNECTION,
            sandbox_id=self.sandbox_id,
        )
        try:
            raw = await self._api.get(endpoint)
        except APIException as exc:
            if exc.status_code == 503:
                raise SandboxException(
                    "e2b-connection unavailable (configure E2B_DROPIN_WS_SECRET on the API server): "
                    f"{exc.message}"
                ) from exc
            raise
        info = E2bConnectionInfo.from_dict(raw)
        if not info.ws_url or not info.traffic_access_token or not info.e2b_style_host:
            raise SandboxException(
                "e2b-connection response missing ws_url, traffic_access_token, or e2b_style_host"
            )
        self._e2b = info
        return info

    def open_agent_websocket(self, *, use_query_token: bool = False, **kwargs: Any):
        """Async context manager from ``websockets.connect`` (same semantics as ``e2b`` shim)."""
        from ..agent_websocket import open_agent_websocket_async

        e2b = self._require_e2b()
        return open_agent_websocket_async(
            e2b.ws_url,
            e2b.traffic_access_token,
            use_query_token=use_query_token,
            **kwargs,
        )

    async def set_timeout(self, seconds: int) -> None:
        """Refresh stored lease (``POST …/timeout``), E2B ``set_timeout`` parity."""
        ts = max(60, min(int(seconds), 604800))
        endpoint = APIEndpoints.format(
            APIEndpoints.SANDBOX_TIMEOUT,
            sandbox_id=self.sandbox_id,
        )
        data = await self._api.post(endpoint, json={"timeout_seconds": ts})
        if not data.get("refreshed"):
            raise SandboxException(f"set_timeout not applied (sandbox not running?): {data!r}")

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
            self._e2b = None
            await self._filesystem.invalidate_envd_connection()
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
