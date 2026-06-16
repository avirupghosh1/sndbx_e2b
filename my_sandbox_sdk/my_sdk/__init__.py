"""
My Sandbox SDK - REST API-based sandbox control client.

Secure sandbox environments for running untrusted code with VM/Container support.

Example:
    ```python
    from my_sdk import Sandbox
    
    # Create sandbox
    sandbox = Sandbox.create(api_url="http://localhost:8000")
    
    # Run command
    result = sandbox.commands.run("echo 'Hello World'")
    print(result.stdout)
    
    sandbox.kill()
    ```

Async example:
    ```python
    from my_sdk import AsyncSandbox
    
    sandbox = await AsyncSandbox.create(api_url="http://localhost:8000")
    result = await sandbox.commands.run("echo 'Hello World'")
    await sandbox.kill()
    ```
"""

__version__ = "0.1.0"

# Sync API
from .sync.sandbox import Sandbox
from .sync.commands import Commands
from .sync.filesystem import Filesystem

from .config import use_envd_filesystem
from .envd_guest_fs import AsyncEnvdGuestFilesystem, EnvdConnectionConfig, EnvdGuestFilesystem

# Async API
from .async_sdk.sandbox import AsyncSandbox
from .async_sdk.commands import AsyncCommands
from .async_sdk.filesystem import AsyncFilesystem

# E2B-style templates (local REST: POST /templates, /templates/from-dockerfile)
from .template import (
    AsyncTemplate,
    Template,
    default_build_logger,
    wait_for_port,
    wait_for_timeout,
)

# Models and exceptions
from .models import (
    SandboxInfo,
    SandboxState,
    SandboxLifecycle,
    E2bConnectionInfo,
    SnapshotRecord,
    CommandResult,
    FilesystemEntry,
    EntryType,
    BuildInfo,
    TemplateDefinition,
)
from .agent_websocket import open_agent_websocket_async, open_agent_websocket_sync

from .exceptions import (
    SandboxException,
    SandboxNotFoundException,
    CommandException,
    FileNotFoundException,
    AuthenticationException,
    TimeoutException,
    InvalidArgumentException,
)

__all__ = [
    # Sync
    "Sandbox",
    "Commands",
    "Filesystem",
    "use_envd_filesystem",
    "EnvdConnectionConfig",
    "EnvdGuestFilesystem",
    "AsyncEnvdGuestFilesystem",
    # Async
    "AsyncSandbox",
    "AsyncCommands",
    "AsyncFilesystem",
    # Templates (E2B-shaped)
    "Template",
    "AsyncTemplate",
    "default_build_logger",
    "wait_for_port",
    "wait_for_timeout",
    # Agent WebSocket (E2B drop-in; requires ``pip install 'my-sandbox-sdk[ws]'``)
    "open_agent_websocket_async",
    "open_agent_websocket_sync",
    # Models
    "SandboxInfo",
    "SandboxState",
    "SandboxLifecycle",
    "E2bConnectionInfo",
    "SnapshotRecord",
    "CommandResult",
    "FilesystemEntry",
    "EntryType",
    "BuildInfo",
    "TemplateDefinition",
    # Exceptions
    "SandboxException",
    "SandboxNotFoundException",
    "CommandException",
    "FileNotFoundException",
    "AuthenticationException",
    "TimeoutException",
    "InvalidArgumentException",
]
