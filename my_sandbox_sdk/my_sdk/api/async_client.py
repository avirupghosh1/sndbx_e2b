"""
Asynchronous REST API client for My Sandbox SDK.
"""

import http.client
import json as json_module
import asyncio
from typing import Optional, Dict, Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlencode

from . import BaseAPIClient, APIEndpoints
from ..config import DEFAULT_SDK_REQUEST_TIMEOUT
from ..exceptions import TimeoutException, SandboxException


class AsyncAPIClient(BaseAPIClient):
    """Asynchronous REST API client using urllib in executor."""
    
    def __init__(
        self,
        api_url: str,
        api_key: Optional[str] = None,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
    ):
        """Initialize asynchronous API client."""
        super().__init__(api_url, api_key, request_timeout)
    
    def _make_request_sync(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Make synchronous HTTP request (called from executor)."""
        url = urljoin(self.api_url, endpoint)
        
        # Add query parameters
        if params:
            query_string = urlencode(params)
            url = f"{url}?{query_string}"
        
        headers = self._get_headers()
        
        req = urllib_request.Request(
            url,
            method=method,
            headers=headers,
        )
        
        # Use `is not None`: `{}` is a valid JSON body (e.g. sandbox create) but falsy in Python.
        if json is not None:
            req.data = json_module.dumps(json).encode("utf-8")
        
        try:
            with urllib_request.urlopen(req, timeout=self.request_timeout) as response:
                status_code = response.status
                data = json_module.loads(response.read().decode("utf-8"))
                return {
                    "status_code": status_code,
                    "data": data,
                }
        except HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            try:
                error_data = json_module.loads(error_body)
            except:
                error_data = error_body
            return {
                "status_code": e.code,
                "data": error_data,
            }
        except URLError as e:
            if isinstance(e.reason, TimeoutError):
                raise TimeoutException(f"Request timeout after {self.request_timeout}s")
            raise SandboxException(f"Connection error: {str(e)}") from e
        except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError) as e:
            raise SandboxException(
                "The server closed the TCP connection before sending any HTTP response. "
                "This is not your urllib read-timeout firing (that would be a timeout error after the full wait). "
                "Typical causes: the API process exited mid-request (often OOM during an in-container `docker pull`), "
                "or the api container restarted. Run `docker compose logs api` and look for Killed, OOM, or tracebacks; "
                "rebuild with the current Dockerfile so startup pre-pull runs, or run `docker pull python:3.11` on the host first."
            ) from e
        except TimeoutError as e:
            raise TimeoutException(f"Request timeout after {self.request_timeout}s") from e
        except Exception as e:
            raise SandboxException(f"Request failed: {str(e)}") from e
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict] = None,
        params: Optional[Dict] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Make asynchronous HTTP request using executor.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            endpoint: API endpoint
            json: JSON body (for POST/PUT/PATCH)
            params: Query parameters
            
        Returns:
            Dictionary with status_code and data keys
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._make_request_sync,
            method,
            endpoint,
            json,
            params,
        )
    
    async def get(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make async GET request."""
        response = await self._make_request("GET", endpoint, **kwargs)
        return self._handle_response(response)
    
    async def post(self, endpoint: str, json: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """Make async POST request."""
        response = await self._make_request("POST", endpoint, json=json, **kwargs)
        return self._handle_response(response)
    
    async def put(self, endpoint: str, json: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """Make async PUT request."""
        response = await self._make_request("PUT", endpoint, json=json, **kwargs)
        return self._handle_response(response)
    
    async def delete(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make async DELETE request."""
        response = await self._make_request("DELETE", endpoint, **kwargs)
        return self._handle_response(response)
    
    async def patch(self, endpoint: str, json: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """Make async PATCH request."""
        response = await self._make_request("PATCH", endpoint, json=json, **kwargs)
        return self._handle_response(response)
