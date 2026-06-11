"""
Synchronous filesystem module for My Sandbox SDK.
"""

import base64
from typing import Optional, List, Dict, Any, Union
from urllib.parse import urljoin

from ..api import APIEndpoints
from ..models import FilesystemEntry, WriteInfo, EntryType
from ..exceptions import FileNotFoundException


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
    
    def list(self, path: str = "/") -> List[FilesystemEntry]:
        """
        List files and directories at a path.
        
        Args:
            path: Directory path to list
            
        Returns:
            List of FilesystemEntry objects
            
        Example:
            ```python
            entries = sandbox.files.list("/home")
            for entry in entries:
                print(f"{entry.name} ({entry.type})")
            ```
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_LIST,
            sandbox_id=self.sandbox_id,
        )
        
        response = self._api.get(endpoint, params={"path": path})
        entries = response.get("entries", [])
        return [FilesystemEntry.from_dict(e) for e in entries]
    
    def read(self, path: str) -> str:
        """
        Read file contents.
        
        Args:
            path: Path to the file
            
        Returns:
            File contents as string
            
        Raises:
            FileNotFoundException: If file doesn't exist
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_READ,
            sandbox_id=self.sandbox_id,
        )
        
        response = self._api.get(endpoint, params={"path": path})
        
        # Check if content is base64 encoded
        if response.get("encoding") == "base64":
            return base64.b64decode(response.get("content", "")).decode("utf-8")
        
        return response.get("content", "")
    
    def write(self, path: str, content: str) -> WriteInfo:
        """
        Write content to a file.
        
        Args:
            path: Path to the file
            content: Content to write
            
        Returns:
            WriteInfo with bytes written
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_WRITE,
            sandbox_id=self.sandbox_id,
        )
        
        body = {
            "path": path,
            "content": content,
        }
        
        response = self._api.post(endpoint, json=body)
        return WriteInfo.from_dict(response)
    
    def delete(self, path: str, recursive: bool = False) -> bool:
        """
        Delete a file or directory.
        
        Args:
            path: Path to delete
            recursive: If True, delete directories recursively
            
        Returns:
            True if deletion was successful
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_DELETE,
            sandbox_id=self.sandbox_id,
        )
        
        body = {
            "path": path,
            "recursive": recursive,
        }
        
        self._api.post(endpoint, json=body)
        return True
    
    def create_directory(self, path: str) -> bool:
        """
        Create a directory.
        
        Args:
            path: Directory path to create
            
        Returns:
            True if directory was created
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_LIST,
            sandbox_id=self.sandbox_id,
        )
        
        body = {
            "path": path,
            "mkdir": True,
        }
        
        self._api.post(endpoint, json=body)
        return True
    
    def upload(self, local_path: str, sandbox_path: str) -> WriteInfo:
        """
        Upload a file from local system to sandbox.
        
        Args:
            local_path: Local file path
            sandbox_path: Path in sandbox to write to
            
        Returns:
            WriteInfo with bytes written
        """
        with open(local_path, 'rb') as f:
            content = f.read()
        
        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_UPLOAD,
            sandbox_id=self.sandbox_id,
        )
        
        # Send as binary with base64 encoding for safety
        body = {
            "path": sandbox_path,
            "content": base64.b64encode(content).decode("utf-8"),
            "encoding": "base64",
        }
        
        response = self._api.post(endpoint, json=body)
        return WriteInfo.from_dict(response)
    
    def download(self, sandbox_path: str, local_path: str) -> int:
        """
        Download a file from sandbox to local system.
        
        Args:
            sandbox_path: Path in sandbox to download from
            local_path: Local path to write to
            
        Returns:
            Number of bytes written
        """
        endpoint = APIEndpoints.format(
            APIEndpoints.FILES_DOWNLOAD,
            sandbox_id=self.sandbox_id,
        )
        
        response = self._api.get(endpoint, params={"path": sandbox_path})
        
        # Check if content is base64 encoded
        if response.get("encoding") == "base64":
            content = base64.b64decode(response.get("content", ""))
        else:
            content = response.get("content", "").encode("utf-8")
        
        with open(local_path, 'wb') as f:
            f.write(content)
        
        return len(content)
    
    def exists(self, path: str) -> bool:
        """
        Check if path exists in sandbox.
        
        Args:
            path: Path to check
            
        Returns:
            True if path exists
        """
        try:
            self.read(path)
            return True
        except FileNotFoundException:
            return False
