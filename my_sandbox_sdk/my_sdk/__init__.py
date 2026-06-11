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

# Async API
from .async_sdk.sandbox import AsyncSandbox
from .async_sdk.commands import AsyncCommands
from .async_sdk.filesystem import AsyncFilesystem

# Models and exceptions
from .models import (
    SandboxInfo,
    SandboxState,
    SandboxLifecycle,
    SnapshotRecord,
    CommandResult,
    FilesystemEntry,
    EntryType,
)
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
    # Async
    "AsyncSandbox",
    "AsyncCommands",
    "AsyncFilesystem",
    # Models
    "SandboxInfo",
    "SandboxState",
    "SandboxLifecycle",
    "SnapshotRecord",
    "CommandResult",
    "FilesystemEntry",
    "EntryType",
    # Exceptions
    "SandboxException",
    "SandboxNotFoundException",
    "CommandException",
    "FileNotFoundException",
    "AuthenticationException",
    "TimeoutException",
    "InvalidArgumentException",
]
