# E2B Python SDK - Detailed Architecture & File Structure Explanation

## Table of Contents
1. [High-Level Architecture](#high-level-architecture)
2. [Layered Architecture](#layered-architecture)
3. [Core Files & Modules](#core-files--modules)
4. [Data Flow](#data-flow)
5. [Communication Protocols](#communication-protocols)
6. [Sync vs Async Implementation](#sync-vs-async-implementation)

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────┐
│           User Application Code                  │
│  (from e2b import Sandbox; sandbox.create())    │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│         E2B Python SDK (Main Layer)             │
│  - Sandbox, AsyncSandbox                        │
│  - Commands, Filesystem, PTY, Git               │
└──────────────────┬──────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
┌───────▼────────┐  ┌────────▼─────────┐
│  API Client    │  │  ENVD RPC Client │
│  (REST/httpx)  │  │  (gRPC/Connect)  │
└───────┬────────┘  └────────┬─────────┘
        │                    │
        │ HTTP               │ gRPC
        ▼                    ▼
┌────────────────────────────────────┐
│   E2B Cloud Infrastructure         │
│  (Sandbox Control Plane)           │
│  - Create/kill sandboxes           │
│  - Manage templates                │
│  - Rate limiting, auth             │
└────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────┐
│   Sandbox Runtime (ENVD)           │
│  - Command execution               │
│  - File operations                 │
│  - Process management              │
│  - Network setup                   │
└────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────┐
│   Isolated Linux Container         │
│  - Python, Node, Docker, etc       │
│  - User code execution space       │
└────────────────────────────────────┘
```

---

## Layered Architecture

### Layer 1: User Interface Layer
**Files**: `sandbox_sync/main.py`, `sandbox_async/main.py`

```python
# What users see and interact with
from e2b import Sandbox, AsyncSandbox

sandbox = Sandbox.create()
result = sandbox.commands.run("python script.py")
sandbox.files.write("/tmp/file.txt", "content")
sandbox.kill()
```

### Layer 2: SDK Abstraction Layer
**Files**: 
- `sandbox_sync/commands.py` - Command execution
- `sandbox_sync/filesystem.py` - File operations  
- `sandbox_sync/pty.py` - Terminal access
- `sandbox_sync/git.py` - Git operations

These provide the **user-friendly API** that abstracts away the complexity.

### Layer 3: Communication Layer
**Files**:
- `api/__init__.py` - REST API client for control plane
- `envd/rpc.py` - gRPC/Connect client for sandbox runtime
- `envd/api.py` - HTTP error handling for ENVD
- `connection_config.py` - Connection configuration

### Layer 4: Protocol & Transport Layer
**Files**:
- Uses `httpx` for HTTP/REST calls (control plane)
- Uses `e2b-connect` library for gRPC calls (sandbox runtime)

---

## Core Files & Modules

### 1. `__init__.py` - Package Exports
```
📄 e2b/__init__.py
Purpose: Exports public API
Content: Imports all public classes from submodules

Key Exports:
- Sandbox, AsyncSandbox (main entry points)
- ConnectionConfig (configuration)
- Various exceptions (SandboxException, TimeoutException, etc.)
- Data models (CommandResult, SandboxInfo, etc.)
```

**Why**: Single import point for users
```python
from e2b import Sandbox, TimeoutException, CommandResult
```

---

### 2. `connection_config.py` - Configuration Management
```
📄 connection_config.py (120 lines)
Purpose: Manage all SDK configuration
```

**What it does**:
- Reads environment variables (`E2B_API_KEY`, `E2B_DOMAIN`, etc.)
- Stores connection credentials
- Manages headers and authentication

**Key Classes**:

```python
class ApiParams(TypedDict):
    request_timeout: Optional[float]      # Timeout for requests
    headers: Optional[Dict[str, str]]     # Custom headers
    api_key: Optional[str]                # API key for auth
    domain: Optional[str]                 # E2B domain (e2b.app)
    api_url: Optional[str]                # Base API URL
    sandbox_url: Optional[str]            # Direct sandbox URL
    proxy: Optional[ProxyTypes]           # HTTP proxy config

class ConnectionConfig:
    def __init__(self, domain, api_key, api_url, ...):
        self.domain = domain or "e2b.app"
        self.api_key = api_key
        self.sandbox_headers = self._build_headers()
        # ... manages all connection details
```

**Data Flow**:
```
Environment Variables → ConnectionConfig → API Client → HTTP Headers
   E2B_API_KEY                                 ↓
   E2B_DOMAIN                          Used for authentication
   E2B_SANDBOX_URL                     Each request has this
```

---

### 3. `exceptions.py` - Error Hierarchy
```
📄 exceptions.py (50+ exception types)
Purpose: Structured error handling
```

**Exception Hierarchy**:
```
Exception
  └─ SandboxException (base)
      ├─ SandboxNotFoundException (404)
      ├─ FileNotFoundException (file not found)
      ├─ CommandExitException (command non-zero exit)
      ├─ TimeoutException (timeout errors)
      ├─ AuthenticationException (invalid API key)
      ├─ RateLimitException (429 errors)
      ├─ GitAuthException (git auth failed)
      ├─ BuildException (template build failed)
      ├─ NotEnoughSpaceException (507 errors)
      └─ ... others
```

**Why Multiple Exceptions**:
Users can catch specific errors:
```python
try:
    result = sandbox.commands.run("cmd")
except TimeoutException:
    print("Command timed out")
except FileNotFoundException:
    print("File not found")
except SandboxException as e:
    print(f"General error: {e}")
```

---

### 4. `api/__init__.py` - REST API Client
```
📄 api/__init__.py (250+ lines)
Purpose: HTTP communication with E2B control plane
```

**What it does**:
- Extends `AuthenticatedClient` from httpx
- Handles authentication headers
- Manages connection pools
- Logs requests/responses
- Validates API keys

**Key Class: `ApiClient`**
```python
class ApiClient(AuthenticatedClient):
    def __init__(self, config, require_api_key=True, ...):
        # Validates API key format
        validate_api_key(config.api_key)
        
        # Sets up authentication
        # X-API-KEY header for control plane
        # Bearer token for some endpoints
        
        # Sets up httpx with proper limits
        limits = Limits(
            max_connections=2000,
            keepalive_expiry=300
        )

    def _log_request(self, request):
        # Logs "Request GET /sandboxes"
    
    def _log_response(self, response):
        # Logs "Response 200" or error
```

**Example Use**:
```python
# Inside SDK (user doesn't call this directly)
api = ApiClient(config)
response = api.get("/sandboxes")  # REST call
sandbox_id = response["sandbox_id"]
```

---

### 5. `envd/rpc.py` - gRPC Error Handling
```
📄 envd/rpc.py (60 lines)
Purpose: Handle gRPC/Connect errors
```

**What it does**:
Maps gRPC status codes to Python exceptions

**Status Code Mapping**:
```python
_DEFAULT_RPC_ERROR_MAP = {
    Code.invalid_argument: InvalidArgumentException,
    Code.unauthenticated: AuthenticationException,
    Code.not_found: NotFoundException,
    Code.unavailable: TimeoutException,
    Code.deadline_exceeded: TimeoutException,
    Code.resource_exhausted: RateLimitException,
}

# Example:
# gRPC returns Code.not_found
# → Converted to NotFoundException in Python
```

**Authentication for gRPC**:
```python
def authentication_header(envd_version, user=None):
    """Creates Basic Auth header for gRPC calls
    
    Example: Authorization: Basic dXNlcjo=
    (base64 encoded "user:")
    """
    value = f"{user}:"
    encoded = base64.b64encode(value.encode()).decode()
    return {"Authorization": f"Basic {encoded}"}
```

---

### 6. `envd/api.py` - HTTP Error Handling
```
📄 envd/api.py (80 lines)
Purpose: Handle HTTP errors from sandbox runtime
```

**Status Code Mapping**:
```python
_DEFAULT_API_ERROR_MAP = {
    400: InvalidArgumentException,
    401: AuthenticationException,
    404: NotFoundException,
    429: RateLimitException,
    502: TimeoutException,
    507: NotEnoughSpaceException,
}
```

**Example**:
```python
# ENVD returns 404 (file not found)
def handle_envd_api_exception(res, error_map):
    if res.status_code == 404:
        raise NotFoundException(res.text)
```

---

### 7. `sandbox_sync/main.py` - Main Sandbox Class (200+ lines)

```
📄 sandbox_sync/main.py
Purpose: Synchronous sandbox management
```

**Class: `Sandbox`**
```python
class Sandbox(SandboxApi):
    """Main sandbox interface - user interacts with this"""
    
    @classmethod
    def create(cls, template: str = "base", ...):
        """Create new sandbox
        
        Steps:
        1. Call REST API: POST /sandboxes
        2. Get sandbox_id back
        3. Create Sandbox instance
        4. Connect to ENVD runtime
        5. Return Sandbox object
        """
        api = ApiClient(config)
        response = api.post("/sandboxes", json={"template": template})
        sandbox_id = response["sandbox_id"]
        
        return cls(
            sandbox_id=sandbox_id,
            api_client=api,
            connection_config=config
        )
    
    def __init__(self, sandbox_id, ...):
        # Store sandbox metadata
        self.sandbox_id = sandbox_id
        self.api_url = f"https://sandbox.{sandbox_id}.e2b.app"
        
        # Create sub-modules
        self._commands = Commands(...)
        self._filesystem = Filesystem(...)
        self._pty = Pty(...)
        self._git = Git(...)
        
        # Create transport for gRPC
        self._transport = get_transport(connection_config)
        
        # Create ENVD HTTP client
        self._envd_api = httpx.Client(
            base_url=self.envd_api_url,
            headers=auth_headers
        )
    
    @property
    def files(self) -> Filesystem:
        """Access filesystem module"""
        return self._filesystem
    
    @property
    def commands(self) -> Commands:
        """Access commands module"""
        return self._commands
    
    def is_running(self) -> bool:
        """Check if sandbox alive"""
        try:
            self._envd_api.get("/health")
            return True
        except:
            return False
    
    def kill(self) -> bool:
        """Kill sandbox"""
        # Call REST API
        api = ApiClient(self.connection_config)
        api.post(f"/sandboxes/{self.sandbox_id}/kill")
        return True
```

**Key Points**:
- `__init__` doesn't call REST API (use `create()`)
- Initializes 4 sub-modules (Commands, Filesystem, PTY, Git)
- Sets up both REST client (for control plane) and gRPC (for runtime)
- Properties provide easy access to sub-modules

---

### 8. `sandbox_sync/commands.py` - Command Execution (150+ lines)

```
📄 sandbox_sync/commands.py
Purpose: Execute commands in sandbox
```

**Class: `Commands`**
```python
class Commands:
    """Execute commands in running sandbox"""
    
    def __init__(self, sandbox_id, api_client, pool, envd_version):
        self._sandbox_id = sandbox_id
        
        # Create gRPC client for command execution
        self._rpc = process_connect.ProcessClient(
            envd_api_url,
            pool=pool,  # Connection pool
            headers=headers,  # Authentication
            json=True  # JSON serialization
        )
    
    def run(
        self,
        command: str,
        cwd: Optional[str] = None,
        env: Optional[Dict] = None,
        timeout: Optional[float] = None,
    ) -> CommandResult:
        """Execute command - BLOCKING
        
        Flow:
        1. Serialize command to protobuf
        2. Send gRPC call to ENVD
        3. Wait for response
        4. Deserialize result
        5. Return CommandResult
        """
        try:
            # Create gRPC request
            request = process_pb2.RunRequest(
                cmd=command,
                cwd=cwd,
                envs=env or {}
            )
            
            # Send to sandbox runtime via gRPC
            result = self._rpc.run(
                request,
                timeout=timeout
            )
            
            # Convert protobuf to Python objects
            return CommandResult(
                exit_code=result.exit_code,
                stdout=result.stdout.decode(),
                stderr=result.stderr.decode()
            )
        except ConnectException as e:
            raise handle_rpc_exception(e)
    
    def list(self) -> List[ProcessInfo]:
        """List running processes"""
        request = process_pb2.ListRequest()
        response = self._rpc.list(request)
        
        processes = []
        for p in response.processes:
            processes.append(ProcessInfo(
                pid=p.pid,
                cmd=p.config.cmd,
                args=list(p.config.args)
            ))
        return processes
    
    def kill(self, pid: int) -> bool:
        """Kill process by PID"""
        request = process_pb2.SendSignalRequest(
            process=process_pb2.ProcessSelector(pid=pid),
            signal=process_pb2.Signal.SIGNAL_SIGKILL
        )
        self._rpc.send_signal(request)
        return True
```

**Key Points**:
- Uses **Protocol Buffers** for serialization (`.proto` files)
- Uses **gRPC** for communication (not REST)
- All methods are **blocking** (synchronous)
- Returns structured data (CommandResult, ProcessInfo)

---

### 9. `sandbox_sync/filesystem.py` - File Operations (300+ lines)

```
📄 sandbox_sync/filesystem.py
Purpose: File operations in sandbox
```

**Class: `Filesystem`**
```python
class Filesystem:
    """File operations in running sandbox"""
    
    def __init__(self, envd_url, envd_version, config, pool, http_client):
        self._envd_api_url = envd_url
        
        # gRPC client for efficient file transfers
        self._rpc = filesystem_connect.FilesystemClient(
            envd_url,
            pool=pool,
            headers=headers
        )
        
        # HTTP client for file streaming
        self._envd_api = http_client
    
    def list(self, path: str = "/") -> List[EntryInfo]:
        """List directory
        
        Uses gRPC for efficiency
        """
        request = filesystem_pb2.ListRequest(path=path)
        response = self._rpc.list(request)
        
        entries = []
        for entry in response.entries:
            entries.append(EntryInfo(
                path=entry.path,
                name=entry.name,
                type=FileType.FILE if entry.is_file else FileType.DIR
            ))
        return entries
    
    def read(
        self,
        path: str,
        format: Literal["text", "bytes", "stream"] = "text"
    ) -> Union[str, bytearray, Iterator[bytes]]:
        """Read file content
        
        - format="text": Returns string (for text files)
        - format="bytes": Returns bytearray (for binary files)
        - format="stream": Returns iterator (for large files)
        """
        if format == "text":
            # Use gRPC for small files
            request = filesystem_pb2.ReadRequest(path=path)
            response = self._rpc.read(request)
            return response.data.decode()
        
        elif format == "bytes":
            # Use gRPC
            request = filesystem_pb2.ReadRequest(path=path)
            response = self._rpc.read(request)
            return bytearray(response.data)
        
        elif format == "stream":
            # Use HTTP streaming for large files
            response = self._envd_api.get(
                f"/files?path={path}",
                stream=True
            )
            return response.iter_bytes()
    
    def write(self, path: str, content: str) -> WriteInfo:
        """Write file
        
        Uses gRPC for efficiency
        """
        request = filesystem_pb2.WriteRequest(
            path=path,
            data=content.encode()
        )
        response = self._rpc.write(request)
        
        return WriteInfo(
            bytes_written=response.bytes_written,
            path=path
        )
    
    def delete(self, path: str, recursive: bool = False):
        """Delete file/directory"""
        request = filesystem_pb2.DeleteRequest(
            path=path,
            recursive=recursive
        )
        self._rpc.delete(request)
    
    def upload(self, local_path: str, sandbox_path: str) -> WriteInfo:
        """Upload file from local to sandbox
        
        Reads local file → streams to sandbox via gRPC
        """
        with open(local_path, 'rb') as f:
            content = f.read()
        
        request = filesystem_pb2.WriteRequest(
            path=sandbox_path,
            data=content
        )
        response = self._rpc.write(request)
        return WriteInfo(bytes_written=len(content))
    
    def download(self, sandbox_path: str, local_path: str):
        """Download file from sandbox to local
        
        Reads from sandbox via gRPC → writes locally
        """
        request = filesystem_pb2.ReadRequest(path=sandbox_path)
        response = self._rpc.read(request)
        
        with open(local_path, 'wb') as f:
            f.write(response.data)
```

**Key Points**:
- Uses gRPC for most operations (efficient binary protocol)
- Uses HTTP streaming for large files
- Multiple read formats (text, bytes, stream)
- Full CRUD operations

---

### 10. `sandbox_async/main.py` - Async Sandbox (Mirror of sync)

```
📄 sandbox_async/main.py
Purpose: Asynchronous sandbox management
```

**Key Difference from Sync**:
```python
class AsyncSandbox:
    @classmethod
    async def create(cls, template: str = "base", ...):
        # Same as sync, but AWAIT on API calls
        api = AsyncApiClient(config)
        response = await api.post("/sandboxes")
        # ... rest is same
    
    async def run_command(self, cmd: str):
        # Async/await instead of blocking
        result = await self._commands.run(cmd)
        return result
```

---

### 11. `sandbox_sync/commands/command_handle.py` - Command Handle (Streaming)

```
📄 sandbox_sync/commands/command_handle.py
Purpose: Handle streaming command output
```

**Class: `CommandHandle`**
```python
class CommandHandle:
    """Handle for executing commands with streaming output"""
    
    def __init__(self, pid, events_generator):
        self._pid = pid
        self._events = events_generator
        self._stdout = ""
        self._stderr = ""
        self._result = None
    
    def __iter__(self):
        """Iterate over output events"""
        for event in self._events:
            if event.data.stdout:
                stdout = event.data.stdout.decode()
                self._stdout += stdout
                yield stdout
            
            if event.data.stderr:
                stderr = event.data.stderr.decode()
                self._stderr += stderr
                yield stderr
    
    def wait(self, on_stdout=None, on_stderr=None) -> CommandResult:
        """Wait for command with callbacks
        
        Useful for real-time output processing
        """
        for stdout, stderr in self:
            if stdout and on_stdout:
                on_stdout(stdout)
            if stderr and on_stderr:
                on_stderr(stderr)
        
        return CommandResult(
            exit_code=self._result.exit_code,
            stdout=self._stdout,
            stderr=self._stderr
        )
```

---

## Data Flow

### Flow 1: Creating a Sandbox
```
User Code:
  sandbox = Sandbox.create(api_key="e2b_...")

↓ (REST API Call)

SDK:
  1. ConnectionConfig reads api_key
  2. ApiClient validates format
  3. POST /sandboxes with headers
  
↓ (HTTP Request)

E2B Control Plane:
  1. Authenticate API key
  2. Create sandbox VM
  3. Start ENVD runtime
  4. Return sandbox_id, access token

↓ (Response)

SDK:
  1. Parse sandbox_id
  2. Connect to sandbox runtime
  3. Create Sandbox object
  4. Initialize Commands, Filesystem, PTY modules
  
↓

Return: Sandbox object
```

### Flow 2: Running a Command
```
User Code:
  result = sandbox.commands.run("python script.py")

↓

SDK (Commands.run method):
  1. Create protobuf request
  2. Serialize arguments
  3. Connect to ENVD via gRPC

↓ (gRPC Call)

Sandbox Runtime (ENVD):
  1. Receive protobuf
  2. Fork process
  3. Execute command
  4. Stream stdout/stderr
  5. Send exit code

↓ (gRPC Response)

SDK:
  1. Deserialize protobuf
  2. Decode stdout/stderr
  3. Create CommandResult object

↓

Return: CommandResult(exit_code=0, stdout="...", stderr="")
```

### Flow 3: Reading a File
```
User Code:
  content = sandbox.files.read("/tmp/file.txt")

↓

SDK (Filesystem.read method):
  1. Create protobuf request
  2. Send gRPC call to ENVD

↓ (gRPC Call)

Sandbox Runtime:
  1. Open file
  2. Read content
  3. Encode as protobuf
  4. Send back

↓ (gRPC Response)

SDK:
  1. Deserialize protobuf
  2. Decode bytes
  3. Return string

↓

Return: "file contents..."
```

---

## Communication Protocols

### Protocol 1: REST/HTTP (for Control Plane)

**Used for**:
- Creating sandboxes (POST /sandboxes)
- Killing sandboxes (POST /sandboxes/{id}/kill)
- Getting sandbox info
- Authentication
- Template management

**Example Request**:
```
POST /sandboxes HTTP/1.1
Host: api.e2b.app
X-API-KEY: e2b_abc123...
Content-Type: application/json

{
  "template": "base",
  "timeout": 3600
}
```

**Example Response**:
```
HTTP/1.1 201 Created

{
  "sandbox_id": "sb-abc123...",
  "sandbox_domain": "sandbox-abc.e2b.app",
  "envd_version": "0.10.5",
  "envd_access_token": "token..."
}
```

### Protocol 2: gRPC/Connect (for Sandbox Runtime)

**Used for**:
- Command execution (fastest)
- File operations (binary-safe)
- Process management
- Real-time streaming

**Why gRPC**:
- Binary protocol (more efficient than JSON)
- Streaming support (stdout/stderr in real-time)
- HTTP/2 multiplexing (faster)
- Type-safe via protobuf

**Example gRPC Call** (serialized as binary):
```protobuf
// client → server
message RunRequest {
  string cmd = 1;
  string cwd = 2;
  map<string, string> envs = 3;
}

// server → client (streaming)
message RunResponse {
  bytes stdout = 1;
  bytes stderr = 2;
  int32 exit_code = 3;
}
```

---

## Sync vs Async Implementation

### Synchronous (`sandbox_sync/`)

```python
# User calls blocking method
result = sandbox.commands.run("python script.py")  # Blocks until done

# Under the hood:
def run(self, command):
    # Make gRPC call
    response = self._rpc.run(request)  # BLOCKS
    # Wait for response
    return CommandResult(...)
```

**Characteristics**:
- Simple, straightforward
- Blocks thread
- Good for scripts, notebooks
- Sequential execution

### Asynchronous (`sandbox_async/`)

```python
# User awaits the coroutine
result = await sandbox.commands.run("python script.py")  # Non-blocking

# Under the hood:
async def run(self, command):
    # Make async gRPC call
    response = await self._rpc.run_async(request)  # Non-blocking
    # Wait for response without blocking thread
    return CommandResult(...)
```

**Characteristics**:
- Complex but efficient
- Non-blocking
- Good for concurrent operations
- Can run many sandboxes in parallel

### Example Comparison

**Sync (Sequential)**:
```python
# Takes ~30 seconds total (10s × 3)
sandbox1 = Sandbox.create()
result1 = sandbox1.commands.run("sleep 10")  # 10s
result2 = sandbox1.commands.run("sleep 10")  # 10s
result3 = sandbox1.commands.run("sleep 10")  # 10s
# Total: 30 seconds
```

**Async (Concurrent)**:
```python
# Takes ~10 seconds total (concurrent)
sandboxes = await asyncio.gather(
    AsyncSandbox.create(),
    AsyncSandbox.create(),
    AsyncSandbox.create(),
)
results = await asyncio.gather(
    sandboxes[0].commands.run("sleep 10"),
    sandboxes[1].commands.run("sleep 10"),
    sandboxes[2].commands.run("sleep 10"),
)
# Total: 10 seconds (parallel execution)
```

---

## Key Design Patterns

### Pattern 1: Composition Over Inheritance

```python
# Sandbox doesn't implement everything
class Sandbox:
    # Instead, it composes sub-modules
    self._commands = Commands(...)
    self._filesystem = Filesystem(...)
    self._pty = Pty(...)
    self._git = Git(...)

# Users access via properties
result = sandbox.commands.run(...)  # delegation
sandbox.files.write(...)             # delegation
```

### Pattern 2: Context Manager

```python
# Resource cleanup
with Sandbox.create() as sandbox:
    result = sandbox.commands.run(...)
# Automatically calls sandbox.kill()
```

### Pattern 3: Overloading (for type hints)

```python
@overload
def read(self, path: str, format: Literal["text"]) -> str: ...

@overload
def read(self, path: str, format: Literal["bytes"]) -> bytearray: ...

@overload
def read(self, path: str, format: Literal["stream"]) -> Iterator[bytes]: ...

def read(self, path, format="text"):
    # One implementation
    # Multiple type signatures for IDE autocomplete
```

### Pattern 4: Error Mapping

```python
# Map protocol-specific errors to Python exceptions

# gRPC errors → Python exceptions
Code.not_found → NotFoundException
Code.unavailable → TimeoutException
Code.unauthenticated → AuthenticationException

# HTTP errors → Python exceptions
404 → NotFoundException
401 → AuthenticationException
429 → RateLimitException
```

---

## File Organization Summary

```
e2b/
├── __init__.py                     # Public API
├── connection_config.py            # Configuration
├── exceptions.py                   # Error types
├── api/
│   └── __init__.py                # REST API client
├── envd/
│   ├── rpc.py                     # gRPC error handling
│   ├── api.py                     # HTTP error handling
│   ├── versions.py                # Version constants
│   ├── process/                   # protobuf definitions
│   └── filesystem/                # protobuf definitions
├── sandbox_sync/
│   ├── main.py                    # Sync Sandbox class
│   ├── commands.py                # Command execution
│   ├── filesystem.py              # File operations
│   ├── pty.py                     # Terminal (PTY)
│   ├── git.py                     # Git operations
│   └── commands/
│       ├── command.py             # gRPC command wrapper
│       └── command_handle.py      # Command output streaming
├── sandbox_async/                 # Same as sync but async
│   ├── main.py
│   ├── commands.py
│   ├── filesystem.py
│   └── ...
├── template/                      # Template building
├── volume/                        # Persistent volumes
└── ... (other features)
```

---

## Summary

**E2B Python SDK** is a sophisticated client library with:

1. **Two-Protocol Architecture**:
   - REST for control plane (create/destroy sandboxes)
   - gRPC for runtime (fast command execution & files)

2. **Layered Design**:
   - User layer (Sandbox API)
   - Abstraction layer (Commands, Filesystem)
   - Communication layer (ApiClient, gRPC client)
   - Protocol layer (httpx, gRPC-Connect)

3. **Dual API**:
   - Sync for simplicity
   - Async for concurrency

4. **Smart Error Handling**:
   - Maps protocol errors to specific exceptions
   - Helps users write robust code

5. **Modular Architecture**:
   - Composition of features (Commands, Filesystem, PTY, Git)
   - Easy to extend and maintain

This design allows E2B to be both **easy to use** (simple API) and **powerful** (high performance, multiple protocols, concurrent execution).
