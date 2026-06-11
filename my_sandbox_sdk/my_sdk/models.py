"""
Data models for My Sandbox SDK.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class SandboxState(str, Enum):
    """States a sandbox can be in."""
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class EntryType(str, Enum):
    """File system entry types."""
    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"


@dataclass
class SandboxInfo:
    """Information about a sandbox."""
    sandbox_id: str
    state: SandboxState
    created_at: str
    updated_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "SandboxInfo":
        """Create from API response dict."""
        return cls(
            sandbox_id=data.get("sandbox_id", ""),
            state=SandboxState(data.get("state", "running")),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SandboxLifecycle:
    """Lightweight liveness from ``GET /sandboxes/{id}/status``."""

    sandbox_id: str
    state: str
    running: bool

    @classmethod
    def from_dict(cls, data: Dict) -> "SandboxLifecycle":
        return cls(
            sandbox_id=data.get("sandbox_id", ""),
            state=str(data.get("state", "")),
            running=bool(data.get("running", False)),
        )


@dataclass
class SnapshotRecord:
    """Filesystem snapshot metadata (Docker ``docker commit``)."""

    snapshot_id: str
    source_sandbox_id: str
    image_ref: str
    label: str
    created_at: str

    @classmethod
    def from_dict(cls, data: Dict) -> "SnapshotRecord":
        return cls(
            snapshot_id=data.get("snapshot_id", ""),
            source_sandbox_id=data.get("source_sandbox_id", ""),
            image_ref=data.get("image_ref", ""),
            label=str(data.get("label", "") or ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class CommandResult:
    """Result of a command execution."""
    exit_code: int
    stdout: str
    stderr: str
    pid: int = 0
    
    @classmethod
    def from_dict(cls, data: Dict) -> "CommandResult":
        """Create from API response dict."""
        return cls(
            exit_code=data.get("exit_code", 0),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            pid=data.get("pid", 0),
        )


@dataclass
class ProcessInfo:
    """Information about a running process."""
    pid: int
    cmd: str
    args: List[str] = field(default_factory=list)
    cwd: str = ""
    envs: Dict[str, str] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ProcessInfo":
        """Create from API response dict."""
        return cls(
            pid=data.get("pid", 0),
            cmd=data.get("cmd", ""),
            args=data.get("args", []),
            cwd=data.get("cwd", ""),
            envs=data.get("envs", {}),
        )


@dataclass
class FilesystemEntry:
    """Information about a filesystem entry."""
    path: str
    name: str
    type: EntryType
    size: int = 0
    mode: int = 0
    modified_at: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict) -> "FilesystemEntry":
        """Create from API response dict."""
        return cls(
            path=data.get("path", ""),
            name=data.get("name", ""),
            type=EntryType(data.get("type", "file")),
            size=data.get("size", 0),
            mode=data.get("mode", 0),
            modified_at=data.get("modified_at"),
        )


@dataclass
class WriteInfo:
    """Information about a file write operation."""
    bytes_written: int
    path: str
    
    @classmethod
    def from_dict(cls, data: Dict) -> "WriteInfo":
        """Create from API response dict."""
        return cls(
            bytes_written=data.get("bytes_written", 0),
            path=data.get("path", ""),
        )


@dataclass
class SandboxMetrics:
    """Metrics for a sandbox."""
    cpu_usage_percent: float
    memory_usage_bytes: int
    disk_usage_bytes: int
    uptime_seconds: int
    
    @classmethod
    def from_dict(cls, data: Dict) -> "SandboxMetrics":
        """Create from API response dict."""
        return cls(
            cpu_usage_percent=data.get("cpu_usage_percent", 0.0),
            memory_usage_bytes=data.get("memory_usage_bytes", 0),
            disk_usage_bytes=data.get("disk_usage_bytes", 0),
            uptime_seconds=data.get("uptime_seconds", 0),
        )
