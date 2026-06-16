"""
Direct HTTP filesystem client for the in-guest ``envd`` daemon (``GET …/envd-connection``).

Used when ``MY_SANDBOX_USE_ENVD_FILESYSTEM`` is enabled. Requires the ``httpx`` package
(``pip install "my-sandbox-sdk[envd]"`` or ``pip install httpx``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import quote

from .api import APIEndpoints
from .exceptions import APIException, AuthenticationException, FileNotFoundException, SandboxException

if TYPE_CHECKING:
    from .api.sync import APIClient
    from .api.async_client import AsyncAPIClient


@dataclass(frozen=True)
class EnvdConnectionConfig:
    """Connection details returned by the control plane ``GET /sandboxes/{id}/envd-connection``."""

    http_base_url: str
    access_token: str

    def validate(self) -> None:
        if not (self.http_base_url or "").strip():
            raise SandboxException("envd-connection: empty http_base_url")
        if not (self.access_token or "").strip():
            raise SandboxException("envd-connection: empty access_token")


def parse_envd_connection_payload(data: Dict[str, Any]) -> EnvdConnectionConfig:
    base = (data.get("http_base_url") or "").rstrip("/")
    tok = (data.get("access_token") or "").strip()
    cfg = EnvdConnectionConfig(http_base_url=base, access_token=tok)
    cfg.validate()
    return cfg


def _require_httpx():
    try:
        import httpx  # noqa: F401
    except ImportError as e:  # pragma: no cover
        raise SandboxException(
            "MY_SANDBOX_USE_ENVD_FILESYSTEM requires httpx. Install: pip install 'my-sandbox-sdk[envd]' "
            "or pip install httpx"
        ) from e
    import httpx

    return httpx


class EnvdGuestFilesystem:
    """Synchronous filesystem operations against the guest envd HTTP server."""

    def __init__(self, config: EnvdConnectionConfig, *, timeout: float) -> None:
        httpx = _require_httpx()
        config.validate()
        self._config = config
        self._timeout = float(timeout)
        self._client = httpx.Client(
            base_url=config.http_base_url.rstrip("/"),
            headers={
                "X-Access-Token": config.access_token,
            },
            timeout=httpx.Timeout(timeout),
        )

    @classmethod
    def connect_via_control_plane(
        cls,
        api_client: "APIClient",
        sandbox_id: str,
        *,
        timeout: float,
    ) -> "EnvdGuestFilesystem":
        endpoint = APIEndpoints.format(APIEndpoints.SANDBOX_ENVD_CONNECTION, sandbox_id=sandbox_id)
        try:
            raw = api_client.get(endpoint)
        except APIException as exc:
            if exc.status_code in (503, 409):
                raise SandboxException(
                    "envd-connection unavailable (enable ENVD_PUBLISH_PORT on the API, Docker/gVisor, "
                    "and ensure the guest daemon is running). "
                    f"HTTP {exc.status_code}: {exc.message}"
                ) from exc
            raise
        cfg = parse_envd_connection_payload(raw)
        return cls(cfg, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def _headers_json(self) -> Dict[str, str]:
        return {
            "X-Access-Token": self._config.access_token,
            "Content-Type": "application/json",
        }

    def _raise_for_guest(self, resp, *, path: str) -> None:
        if resp.status_code == 404:
            raise FileNotFoundException(path)
        if resp.status_code == 401:
            raise AuthenticationException("envd guest rejected X-Access-Token (401)")
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise SandboxException(f"envd guest HTTP {resp.status_code}: {detail}")

    def list_dir(self, path: str = "/") -> List[Dict[str, Any]]:
        r = self._client.post("/v1/fs/list_dir", headers=self._headers_json(), json={"path": path})
        self._raise_for_guest(r, path=path)
        data = r.json()
        return list(data.get("entries") or [])

    def stat(self, path: str) -> Dict[str, Any]:
        r = self._client.post("/v1/fs/stat", headers=self._headers_json(), json={"path": path})
        self._raise_for_guest(r, path=path)
        return dict(r.json().get("entry") or {})

    def mkdir(self, path: str) -> None:
        r = self._client.post("/v1/fs/mkdir", headers=self._headers_json(), json={"path": path})
        if r.status_code == 409:
            return
        self._raise_for_guest(r, path=path)

    def remove(self, path: str) -> None:
        r = self._client.post("/v1/fs/remove", headers=self._headers_json(), json={"path": path})
        self._raise_for_guest(r, path=path)

    def read_bytes(self, path: str) -> bytes:
        r = self._client.get(f"/files?path={quote(path, safe='')}")
        self._raise_for_guest(r, path=path)
        return r.content

    def write_bytes(self, path: str, body: bytes) -> Dict[str, Any]:
        r = self._client.post(
            f"/files?path={quote(path, safe='')}",
            headers={
                "X-Access-Token": self._config.access_token,
                "Content-Type": "application/octet-stream",
            },
            content=body,
        )
        self._raise_for_guest(r, path=path)
        try:
            return dict(r.json())
        except json.JSONDecodeError:
            return {"path": path, "bytes_written": len(body)}


class AsyncEnvdGuestFilesystem:
    """Async filesystem operations against the guest envd HTTP server."""

    def __init__(self, config: EnvdConnectionConfig, *, timeout: float) -> None:
        httpx = _require_httpx()
        config.validate()
        self._config = config
        self._timeout = float(timeout)
        self._client = httpx.AsyncClient(
            base_url=config.http_base_url.rstrip("/"),
            headers={"X-Access-Token": config.access_token},
            timeout=httpx.Timeout(timeout),
        )

    @classmethod
    async def connect_via_control_plane(
        cls,
        api_client: "AsyncAPIClient",
        sandbox_id: str,
        *,
        timeout: float,
    ) -> "AsyncEnvdGuestFilesystem":
        endpoint = APIEndpoints.format(APIEndpoints.SANDBOX_ENVD_CONNECTION, sandbox_id=sandbox_id)
        try:
            raw = await api_client.get(endpoint)
        except APIException as exc:
            if exc.status_code in (503, 409):
                raise SandboxException(
                    "envd-connection unavailable (enable ENVD_PUBLISH_PORT on the API, Docker/gVisor, "
                    "and ensure the guest daemon is running). "
                    f"HTTP {exc.status_code}: {exc.message}"
                ) from exc
            raise
        cfg = parse_envd_connection_payload(raw)
        return cls(cfg, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers_json(self) -> Dict[str, str]:
        return {
            "X-Access-Token": self._config.access_token,
            "Content-Type": "application/json",
        }

    async def _raise_for_guest(self, resp, *, path: str) -> None:
        if resp.status_code == 404:
            raise FileNotFoundException(path)
        if resp.status_code == 401:
            raise AuthenticationException("envd guest rejected X-Access-Token (401)")
        if resp.status_code >= 400:
            try:
                data = resp.json()
                detail = data.get("detail", resp.text) if isinstance(data, dict) else resp.text
            except Exception:
                detail = getattr(resp, "text", "") or ""
            raise SandboxException(f"envd guest HTTP {resp.status_code}: {detail}")

    async def list_dir(self, path: str = "/") -> List[Dict[str, Any]]:
        r = await self._client.post("/v1/fs/list_dir", headers=self._headers_json(), json={"path": path})
        await self._raise_for_guest(r, path=path)
        data = r.json()
        return list(data.get("entries") or [])

    async def stat(self, path: str) -> Dict[str, Any]:
        r = await self._client.post("/v1/fs/stat", headers=self._headers_json(), json={"path": path})
        await self._raise_for_guest(r, path=path)
        return dict(r.json().get("entry") or {})

    async def mkdir(self, path: str) -> None:
        r = await self._client.post("/v1/fs/mkdir", headers=self._headers_json(), json={"path": path})
        if r.status_code == 409:
            return
        await self._raise_for_guest(r, path=path)

    async def remove(self, path: str) -> None:
        r = await self._client.post("/v1/fs/remove", headers=self._headers_json(), json={"path": path})
        await self._raise_for_guest(r, path=path)

    async def read_bytes(self, path: str) -> bytes:
        r = await self._client.get(f"/files?path={quote(path, safe='')}")
        await self._raise_for_guest(r, path=path)
        return r.content

    async def write_bytes(self, path: str, body: bytes) -> Dict[str, Any]:
        r = await self._client.post(
            f"/files?path={quote(path, safe='')}",
            headers={
                "X-Access-Token": self._config.access_token,
                "Content-Type": "application/octet-stream",
            },
            content=body,
        )
        await self._raise_for_guest(r, path=path)
        try:
            return dict(r.json())
        except json.JSONDecodeError:
            return {"path": path, "bytes_written": len(body)}
