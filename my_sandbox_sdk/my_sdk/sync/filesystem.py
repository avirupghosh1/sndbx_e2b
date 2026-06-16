"""
Synchronous filesystem module for My Sandbox SDK.
"""

import base64
from typing import List, Optional

from ..api import APIEndpoints
from ..config import use_envd_filesystem
from ..envd_guest_fs import EnvdGuestFilesystem
from ..exceptions import FileNotFoundException
from ..models import FilesystemEntry, WriteInfo


class Filesystem:
    """Synchronous module for filesystem operations in sandbox."""

    def __init__(self, sandbox_id: str, api_client):
        """
        Initialize filesystem module.

        Args:
            sandbox_id: ID of the sandbox
            api_client: API client instance
        """
        self.sandbox_id = sandbox_id
        self._api = api_client
        self._envd: Optional[EnvdGuestFilesystem] = None

    def invalidate_envd_connection(self) -> None:
        """Drop cached guest client (e.g. after ``sandbox.kill()``). Safe to call anytime."""
        if self._envd is not None:
            try:
                self._envd.close()
            except Exception:
                pass
            self._envd = None

    def _request_timeout(self) -> float:
        return float(getattr(self._api, "request_timeout", 600.0) or 600.0)

    def _guest(self) -> EnvdGuestFilesystem:
        if self._envd is None:
            self._envd = EnvdGuestFilesystem.connect_via_control_plane(
                self._api,
                self.sandbox_id,
                timeout=self._request_timeout(),
            )
        return self._envd

    def list(self, path: str = "/") -> List[FilesystemEntry]:
        if use_envd_filesystem():
            raw = self._guest().list_dir(path)
            return [FilesystemEntry.from_envd_entry_dict(e) for e in raw]

        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_LIST,
            sandbox_id=self.sandbox_id,
        )
        response = self._api.get(endpoint, params={"path": path})
        entries = response.get("entries", [])
        return [FilesystemEntry.from_dict(e) for e in entries]

    def read(self, path: str) -> str:
        if use_envd_filesystem():
            return self._guest().read_bytes(path).decode("utf-8", errors="replace")

        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_READ,
            sandbox_id=self.sandbox_id,
        )
        response = self._api.get(endpoint, params={"path": path})
        if response.get("encoding") == "base64":
            return base64.b64decode(response.get("content", "")).decode("utf-8")
        return response.get("content", "")

    def write(self, path: str, content: str) -> WriteInfo:
        if use_envd_filesystem():
            body = content.encode("utf-8")
            raw = self._guest().write_bytes(path, body)
            return WriteInfo(
                bytes_written=int(raw.get("bytes_written", len(body))),
                path=str(raw.get("path", path)),
            )

        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_WRITE,
            sandbox_id=self.sandbox_id,
        )
        response = self._api.post(
            endpoint,
            json={
                "path": path,
                "content": content,
            },
        )
        return WriteInfo.from_dict(response)

    def delete(self, path: str, recursive: bool = False) -> bool:
        if use_envd_filesystem():
            if recursive:
                raise NotImplementedError(
                    "MY_SANDBOX_USE_ENVD_FILESYSTEM: guest envd API has no recursive delete; "
                    "set MY_SANDBOX_USE_ENVD_FILESYSTEM=0 or call delete with recursive=False"
                )
            self._guest().remove(path)
            return True

        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_DELETE,
            sandbox_id=self.sandbox_id,
        )
        self._api.post(
            endpoint,
            json={
                "path": path,
                "recursive": recursive,
            },
        )
        return True

    def create_directory(self, path: str) -> bool:
        if use_envd_filesystem():
            self._guest().mkdir(path)
            return True

        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_LIST,
            sandbox_id=self.sandbox_id,
        )
        self._api.post(
            endpoint,
            json={
                "path": path,
                "mkdir": True,
            },
        )
        return True

    def upload(self, local_path: str, sandbox_path: str) -> WriteInfo:
        with open(local_path, "rb") as f:
            content = f.read()

        if use_envd_filesystem():
            raw = self._guest().write_bytes(sandbox_path, content)
            return WriteInfo(
                bytes_written=int(raw.get("bytes_written", len(content))),
                path=str(raw.get("path", sandbox_path)),
            )

        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_UPLOAD,
            sandbox_id=self.sandbox_id,
        )
        body = {
            "path": sandbox_path,
            "content": base64.b64encode(content).decode("utf-8"),
            "encoding": "base64",
        }
        response = self._api.post(endpoint, json=body)
        return WriteInfo.from_dict(response)

    def download(self, sandbox_path: str, local_path: str) -> int:
        if use_envd_filesystem():
            content = self._guest().read_bytes(sandbox_path)
            with open(local_path, "wb") as f:
                f.write(content)
            return len(content)

        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_DOWNLOAD,
            sandbox_id=self.sandbox_id,
        )
        response = self._api.get(endpoint, params={"path": sandbox_path})
        if response.get("encoding") == "base64":
            content = base64.b64decode(response.get("content", ""))
        else:
            content = response.get("content", "").encode("utf-8")
        with open(local_path, "wb") as f:
            f.write(content)
        return len(content)

    def exists(self, path: str) -> bool:
        if use_envd_filesystem():
            try:
                self._guest().stat(path)
                return True
            except FileNotFoundException:
                return False

        try:
            self.read(path)
            return True
        except FileNotFoundException:
            return False
