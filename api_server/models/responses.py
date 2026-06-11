"""Response schemas (Pydantic models)."""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime


class SandboxResponse(BaseModel):
    """Sandbox info response."""
    sandbox_id: str = Field(..., description="Sandbox ID")
    state: str = Field(..., description="Sandbox state")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Update timestamp")
    metadata: Optional[Dict[str, Any]] = Field(default={}, description="Custom metadata")
    container_id: Optional[str] = Field(default=None, description="Container ID")
    runtime: str = Field(
        default="docker",
        description="Engine label: ``docker``, ``gvisor`` (Docker + ``runsc``), or ``firecracker`` (KVM microVM).",
    )

    class Config:
        schema_extra = {
            "example": {
                "sandbox_id": "sb-abc123",
                "state": "running",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "metadata": {"purpose": "testing"},
                "container_id": "abc123...",
            }
        }


class SandboxLifecycleResponse(BaseModel):
    """Lightweight liveness: DB row state + runtime probe."""

    sandbox_id: str
    state: str
    running: bool


class SnapshotRecordResponse(BaseModel):
    """One row from ``docker commit`` + SQLite ``sandbox_snapshots``."""

    snapshot_id: str
    source_sandbox_id: str
    image_ref: str
    label: str
    created_at: str


class TemplateDefinitionResponse(BaseModel):
    """Registered logical template (custom Docker warm path)."""

    template_id: str
    base_image: str
    env: Dict[str, str] = Field(default_factory=dict)
    start_cmd: str
    settle_seconds: int
    warm_snapshot_image: Optional[str] = None
    build_error: Optional[str] = None
    created_at: str
    updated_at: str


class CommandResponse(BaseModel):
    """Command execution response."""
    exit_code: int = Field(..., description="Exit code")
    stdout: str = Field(..., description="Standard output")
    stderr: str = Field(..., description="Standard error")
    pid: int = Field(..., description="Process ID")
    execution_time: float = Field(..., description="Execution time in seconds")

    class Config:
        schema_extra = {
            "example": {
                "exit_code": 0,
                "stdout": "Hello, World!",
                "stderr": "",
                "pid": 1234,
                "execution_time": 0.123
            }
        }


class FileEntryResponse(BaseModel):
    """File entry info."""
    path: str = Field(..., description="Full path")
    name: str = Field(..., description="File name")
    type: str = Field(..., description="Entry type (file/directory)")
    size: int = Field(..., description="File size in bytes")
    permissions: str = Field(..., description="Symbolic mode from ls (e.g. drwxr-xr-x)")
    modified_at: str = Field(default="", description="mtime columns from ls when available")

    class Config:
        schema_extra = {
            "example": {
                "path": "/tmp/file.txt",
                "name": "file.txt",
                "type": "file",
                "size": 1024,
                "permissions": "-rw-r--r--",
                "modified_at": "Jun 4 12:00",
            }
        }


class ListFilesResponse(BaseModel):
    """List files response."""
    path: str = Field(..., description="Directory path")
    entries: List[FileEntryResponse] = Field(..., description="File entries")

    class Config:
        schema_extra = {
            "example": {
                "path": "/tmp",
                "entries": []
            }
        }


class WriteFileResponse(BaseModel):
    """Write file response."""
    path: str = Field(..., description="File path")
    bytes_written: int = Field(..., description="Bytes written")
    success: bool = Field(..., description="Success status")

    class Config:
        schema_extra = {
            "example": {
                "path": "/tmp/file.txt",
                "bytes_written": 1024,
                "success": True
            }
        }


class AgentResponse(BaseModel):
    """Agent info response."""
    agent_id: str = Field(..., description="Agent ID")
    agent_name: str = Field(..., description="Agent name")
    state: str = Field(..., description="Agent state")
    created_at: str = Field(..., description="Creation timestamp")
    config: Optional[Dict[str, Any]] = Field(default={}, description="Agent config")
    last_heartbeat: Optional[str] = Field(default=None, description="Last heartbeat")

    class Config:
        schema_extra = {
            "example": {
                "agent_id": "agent-123",
                "agent_name": "echo_agent",
                "state": "running",
                "created_at": "2024-01-01T00:00:00Z",
                "config": {"debug": True},
                "last_heartbeat": "2024-01-01T00:05:00Z"
            }
        }


class AgentMessageResponse(BaseModel):
    """Agent message response."""
    agent_id: str = Field(..., description="Agent ID")
    message_id: str = Field(..., description="Message ID")
    message_type: str = Field(..., description="Message type")
    content: Dict[str, Any] = Field(..., description="Message content")
    timestamp: str = Field(..., description="Timestamp")
    processed: bool = Field(..., description="Processed status")

    class Config:
        schema_extra = {
            "example": {
                "agent_id": "agent-123",
                "message_id": "msg-456",
                "message_type": "task",
                "content": {"task": "analyze"},
                "timestamp": "2024-01-01T00:00:00Z",
                "processed": True
            }
        }


class ErrorResponse(BaseModel):
    """Error response."""
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    status_code: int = Field(..., description="HTTP status code")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional details")

    class Config:
        schema_extra = {
            "example": {
                "error": "SandboxNotFoundException",
                "message": "Sandbox not found",
                "status_code": 404,
                "details": {"sandbox_id": "sb-123"}
            }
        }
