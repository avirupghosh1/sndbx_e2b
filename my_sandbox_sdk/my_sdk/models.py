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
class E2bConnectionInfo:
    """Minted WebSocket connection metadata from ``GET /sandboxes/{id}/e2b-connection`` (E2B drop-in)."""

    sandbox_id: str
    ws_url: str
    traffic_access_token: str
    e2b_style_host: str
    agent_port: int = 8765

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "E2bConnectionInfo":
        return cls(
            sandbox_id=str(data.get("sandbox_id") or ""),
            ws_url=str(data.get("ws_url") or "").strip(),
            traffic_access_token=str(data.get("traffic_access_token") or "").strip(),
            e2b_style_host=str(data.get("e2b_style_host") or "").strip(),
            agent_port=int(data.get("agent_port") or 8765),
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
    def from_envd_entry_dict(cls, data: Dict) -> "FilesystemEntry":
        """Map envd guest ``/v1/fs/*`` entry payloads to :class:`FilesystemEntry`."""
        raw_type = str(data.get("type", ""))
        if raw_type == "FILE_TYPE_DIRECTORY":
            et = EntryType.DIRECTORY
        elif raw_type == "FILE_TYPE_FILE":
            et = EntryType.FILE
        else:
            et = EntryType.FILE
        return cls(
            path=str(data.get("path", "")),
            name=str(data.get("name", "")),
            type=et,
            size=int(data.get("size", 0) or 0),
            mode=int(data.get("mode", 0) or 0),
            modified_at=data.get("modified_at"),
        )

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
class BuildInfo:
    """Result of ``Template.build`` (E2B-compatible field names; local API has no async build id).

    E2B returns ``name``, ``template_id``, ``build_id`` from their cloud builder. This SDK sets
    ``build_id`` to ``None`` because registration/build is synchronous on your API host.
    """

    name: str
    template_id: str
    build_id: Optional[str] = None
    definition: Optional[Dict[str, Any]] = None

    @classmethod
    def from_api(cls, name: str, template_id: str, data: Dict[str, Any]) -> "BuildInfo":
        return cls(name=name, template_id=template_id, build_id=None, definition=dict(data))


@dataclass
class TemplateDefinition:
    """Logical template row returned by ``GET/POST /templates`` (subset of API fields)."""

    template_id: str
    base_image: str
    env: Dict[str, str] = field(default_factory=dict)
    start_cmd: str = ""
    settle_seconds: int = 20
    ready_cmd: str = ""
    warm_snapshot_image: Optional[str] = None
    build_error: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemplateDefinition":
        return cls(
            template_id=str(data.get("template_id", "")),
            base_image=str(data.get("base_image", "")),
            env=dict(data.get("env") or {}),
            start_cmd=str(data.get("start_cmd") or ""),
            settle_seconds=int(data.get("settle_seconds") or 20),
            ready_cmd=str(data.get("ready_cmd") or ""),
            warm_snapshot_image=data.get("warm_snapshot_image"),
            build_error=data.get("build_error"),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
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
