"""
Base REST API client for My Sandbox SDK.
"""

import json
from typing import Any, Dict, Generic, Iterator, Optional, TypeVar
from abc import ABC, abstractmethod
from dataclasses import asdict

from ..config import DEFAULT_SDK_REQUEST_TIMEOUT
from ..exceptions import (
    APIException,
    AuthenticationException,
    SandboxNotFoundException,
    SandboxException,
    TimeoutException,
)

T = TypeVar("T")


def _error_message_from_body(data: Any) -> str:
    """Build a readable error string from JSON error bodies (FastAPI, this API, etc.)."""
    if not isinstance(data, dict):
        return str(data) if data is not None else "Unknown error"
    msg = data.get("message")
    if isinstance(msg, str) and msg.strip():
        return msg
    detail = data.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail
    if isinstance(detail, list):
        return json.dumps(detail)
    err = data.get("error")
    if isinstance(err, str) and err.strip():
        return err
    return "Unknown error"


class BaseAPIClient(ABC):
    """Base class for REST API clients."""
    
    def __init__(
        self,
        api_url: str,
        api_key: Optional[str] = None,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
    ):
        """
        Initialize API client.
        
        Args:
            api_url: Base URL for the API server (e.g., http://localhost:8000)
            api_key: Optional API key for authentication
            request_timeout: Timeout for requests in seconds
        """
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.request_timeout = request_timeout
        self._session = None
    
    def _get_headers(self) -> Dict[str, str]:
        """Get default headers for requests."""
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            # Must match api_server middleware (X-API-Key), not Bearer.
            headers["X-API-Key"] = self.api_key
        return headers
    
    @abstractmethod
    def _make_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make HTTP request (to be implemented by sync/async subclasses)."""
        pass
    
    def _handle_response(self, response_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle API response.
        
        Args:
            response_dict: Dictionary with status_code and data keys
            
        Returns:
            Response data
            
        Raises:
            APIException: If response indicates an error
        """
        status_code = response_dict.get("status_code", 500)
        data = response_dict.get("data")
        
        if status_code == 401:
            raise AuthenticationException("Authentication failed. Check your API key.")
        elif status_code == 404:
            # Starlette/FastAPI uses {"detail":"Not Found"} when no route matches — easy to confuse
            # with "sandbox missing" because this client historically used a generic message.
            if isinstance(data, dict):
                app_msg = data.get("message")
                if isinstance(app_msg, str) and app_msg.strip():
                    raise SandboxNotFoundException(app_msg.strip())
                detail = data.get("detail")
                if detail == "Not Found":
                    raise SandboxNotFoundException(
                        "HTTP 404: no matching API route. Check `api_url` (must include the server root, "
                        "e.g. http://127.0.0.1:8000). If you are calling snapshot APIs, restart or redeploy "
                        "the API server so `POST /sandboxes/{id}/snapshot` is registered."
                    )
            msg = _error_message_from_body(data)
            raise SandboxNotFoundException(msg or "Resource not found.")
        elif status_code >= 400:
            error_msg = _error_message_from_body(data)
            raise APIException(status_code, error_msg)
        
        return data or {}
    
    def get(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make GET request."""
        response = self._make_request("GET", endpoint, **kwargs)
        return self._handle_response(response)
    
    def post(self, endpoint: str, json: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """Make POST request."""
        response = self._make_request("POST", endpoint, json=json, **kwargs)
        return self._handle_response(response)
    
    def put(self, endpoint: str, json: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """Make PUT request."""
        response = self._make_request("PUT", endpoint, json=json, **kwargs)
        return self._handle_response(response)
    
    def delete(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make DELETE request."""
        response = self._make_request("DELETE", endpoint, **kwargs)
        return self._handle_response(response)
    
    def patch(self, endpoint: str, json: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """Make PATCH request."""
        response = self._make_request("PATCH", endpoint, json=json, **kwargs)
        return self._handle_response(response)

    def iter_post_sse(self, endpoint: str, json_body: Optional[Dict] = None) -> Iterator[Dict[str, Any]]:
        """POST and parse ``text/event-stream`` bodies: each ``data:`` line is one JSON object."""
        from urllib.parse import urljoin
        from urllib import request as urllib_request
        from urllib.error import HTTPError, URLError

        url = urljoin(self.api_url, endpoint)
        req = urllib_request.Request(
            url,
            method="POST",
            headers=self._get_headers(),
            data=json.dumps(json_body if json_body is not None else {}).encode("utf-8"),
        )
        try:
            with urllib_request.urlopen(req, timeout=self.request_timeout) as response:
                while True:
                    raw = response.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        payload = line[5:].strip()
                        if not payload:
                            continue
                        yield json.loads(payload)
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            try:
                data = json.loads(body) if body.strip() else {}
            except json.JSONDecodeError:
                data = {"detail": body}
            self._handle_response({"status_code": e.code, "data": data})
        except URLError as e:
            if isinstance(e.reason, TimeoutError):
                raise TimeoutException(f"Request timeout after {self.request_timeout}s") from e
            raise SandboxException(f"Connection error: {e}") from e


class APIEndpoints:
    """API endpoint constants."""
    
    # Sandbox endpoints
    SANDBOXES = "/sandboxes"
    SANDBOX = "/sandboxes/{sandbox_id}"
    SANDBOX_CREATE = "/sandboxes"
    SANDBOX_KILL = "/sandboxes/{sandbox_id}/kill"
    SANDBOX_PAUSE = "/sandboxes/{sandbox_id}/pause"
    SANDBOX_RESUME = "/sandboxes/{sandbox_id}/resume"
    SANDBOX_STATUS = "/sandboxes/{sandbox_id}/status"
    SANDBOX_SNAPSHOT = "/sandboxes/{sandbox_id}/snapshot"
    SANDBOX_SNAPSHOTS_LIST = "/sandboxes/{sandbox_id}/snapshots"
    SANDBOX_METRICS = "/sandboxes/{sandbox_id}/metrics"
    
    # Commands endpoints
    COMMANDS_RUN = "/sandboxes/{sandbox_id}/commands/run"
    COMMANDS_RUN_STREAM = "/sandboxes/{sandbox_id}/commands/run/stream"
    COMMANDS_LIST = "/sandboxes/{sandbox_id}/commands"
    COMMANDS_KILL = "/sandboxes/{sandbox_id}/commands/{pid}/kill"
    
    # Filesystem endpoints
    FILES_LIST = "/sandboxes/{sandbox_id}/files"
    FILES_READ = "/sandboxes/{sandbox_id}/files/read"
    FILES_WRITE = "/sandboxes/{sandbox_id}/files/write"
    FILES_DELETE = "/sandboxes/{sandbox_id}/files/delete"
    FILES_UPLOAD = "/sandboxes/{sandbox_id}/files/upload"
    FILES_DOWNLOAD = "/sandboxes/{sandbox_id}/files/download"

    # Agent endpoints (API process runs agent threads; agent code executes inside the sandbox container)
    AGENTS_LIST = "/sandboxes/{sandbox_id}/agents"
    AGENTS_SPAWN = "/sandboxes/{sandbox_id}/agents/spawn"
    AGENT_GET = "/sandboxes/{sandbox_id}/agents/{agent_id}"
    AGENT_KILL = "/sandboxes/{sandbox_id}/agents/{agent_id}/kill"

    @staticmethod
    def format(endpoint: str, **kwargs) -> str:
        """Format endpoint with parameters."""
        return endpoint.format(**kwargs)
