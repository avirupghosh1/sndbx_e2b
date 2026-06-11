# My Sandbox SDK

A powerful Python SDK for controlling sandboxed environments via REST API. Designed as a modern replacement for E2B with minimal dependencies.

## Features

- **REST API-first**: Connect to any sandbox control server via REST API
- **Dual API**: Both synchronous and asynchronous interfaces
- **Core Essentials**: Sandbox management, command execution, filesystem operations
- **No Heavy Dependencies**: Uses only Python standard library (urllib) for now
- **Type Hints**: Full type hint support for IDE autocompletion
- **Context Managers**: Clean resource management with automatic cleanup
- **Metrics**: Real-time CPU, memory, and disk usage monitoring

## Installation

```bash
pip install -e .
```

Or copy the `my_sdk` directory to your project.

## Quick Start

### Synchronous API

```python
from my_sdk import Sandbox

# Create sandbox
sandbox = Sandbox.create(api_url="http://localhost:8000")

# Run command
result = sandbox.commands.run("echo 'Hello World'")
print(result.stdout)  # Hello World
print(result.exit_code)  # 0

# Kill sandbox
sandbox.kill()
```

### Asynchronous API

```python
import asyncio
from my_sdk import AsyncSandbox

async def main():
    # Create sandbox
    sandbox = await AsyncSandbox.create(api_url="http://localhost:8000")
    
    # Run command
    result = await sandbox.commands.run("echo 'Hello World'")
    print(result.stdout)  # Hello World
    
    # Kill sandbox
    await sandbox.kill()

asyncio.run(main())
```

### Context Manager (Auto-Cleanup)

```python
from my_sdk import Sandbox

with Sandbox.create(api_url="http://localhost:8000") as sandbox:
    result = sandbox.commands.run("ls -la")
    print(result.stdout)
# Sandbox automatically killed on exit
```

## Core APIs

### Sandbox Management

```python
sandbox = Sandbox.create(api_url="http://localhost:8000")

# Get sandbox info
info = sandbox.info()
print(info.state)  # SandboxState.RUNNING

# Check if running
if sandbox.is_running():
    print("Sandbox is active")

# Pause sandbox
sandbox.pause()

# Resume sandbox
sandbox.resume()

# Get metrics
metrics = sandbox.metrics()
print(f"CPU: {metrics.cpu_usage_percent}%")
print(f"Memory: {metrics.memory_usage_bytes} bytes")

# Kill sandbox
sandbox.kill()
```

### Command Execution

```python
# Simple command
result = sandbox.commands.run("echo 'Hello'")
print(result.stdout)
print(result.stderr)
print(result.exit_code)

# With working directory
result = sandbox.commands.run("ls", cwd="/tmp")

# With environment variables
result = sandbox.commands.run(
    "echo $MY_VAR",
    env={"MY_VAR": "value"}
)

# With timeout
result = sandbox.commands.run("sleep 5", timeout=10)

# List running processes
processes = sandbox.commands.list()
for proc in processes:
    print(f"PID {proc.pid}: {proc.cmd}")

# Kill process
sandbox.commands.kill(pid=12345)
```

### Filesystem Operations

```python
# List directory
entries = sandbox.files.list("/home")
for entry in entries:
    print(f"{entry.name} ({entry.type})")

# Read file
content = sandbox.files.read("/etc/hostname")
print(content)

# Write file
info = sandbox.files.write("/tmp/file.txt", "Hello World")
print(f"Wrote {info.bytes_written} bytes")

# Delete file
sandbox.files.delete("/tmp/file.txt")

# Create directory
sandbox.files.create_directory("/tmp/mydir")

# Upload local file to sandbox
sandbox.files.upload("local_file.txt", "/tmp/uploaded.txt")

# Download file from sandbox
sandbox.files.download("/tmp/file.txt", "local_file.txt")

# Check if file exists
if sandbox.files.exists("/tmp/file.txt"):
    print("File exists")
```

## Configuration

Configure via environment variables:

```bash
export MY_SDK_API_URL="http://localhost:8000"
export MY_SDK_API_KEY="your-api-key"
export MY_SDK_REQUEST_TIMEOUT="30"
```

Or pass directly:

```python
sandbox = Sandbox.create(
    api_url="http://localhost:8000",
    api_key="your-api-key",
)
```

## API Server Requirements

The SDK expects a REST API server implementing these endpoints:

### Sandbox Endpoints
- `POST /sandboxes` - Create sandbox
- `GET /sandboxes/{sandbox_id}` - Get sandbox info
- `POST /sandboxes/{sandbox_id}/kill` - Kill sandbox
- `POST /sandboxes/{sandbox_id}/pause` - Pause sandbox
- `POST /sandboxes/{sandbox_id}/resume` - Resume sandbox
- `GET /sandboxes/{sandbox_id}/metrics` - Get metrics

### Commands Endpoints
- `POST /sandboxes/{sandbox_id}/commands/run` - Run command
- `GET /sandboxes/{sandbox_id}/commands` - List processes
- `POST /sandboxes/{sandbox_id}/commands/{pid}/kill` - Kill process

### Filesystem Endpoints
- `GET /sandboxes/{sandbox_id}/files` - List directory
- `GET /sandboxes/{sandbox_id}/files/read` - Read file
- `POST /sandboxes/{sandbox_id}/files/write` - Write file
- `POST /sandboxes/{sandbox_id}/files/delete` - Delete file
- `POST /sandboxes/{sandbox_id}/files/upload` - Upload file
- `GET /sandboxes/{sandbox_id}/files/download` - Download file

### Response Format

All endpoints should return JSON:

```json
{
  "status_code": 200,
  "data": {
    "sandbox_id": "sb-123",
    "state": "running",
    ...
  }
}
```

Error responses:

```json
{
  "status_code": 404,
  "data": {
    "error": "Sandbox not found"
  }
}
```

## Error Handling

```python
from my_sdk import (
    SandboxException,
    SandboxNotFoundException,
    CommandException,
    FileNotFoundException,
    TimeoutException,
    AuthenticationException,
)

try:
    sandbox = Sandbox.create(api_url="http://localhost:8000")
    result = sandbox.commands.run("python invalid_file.py", timeout=5)
except TimeoutException:
    print("Command timed out")
except CommandException as e:
    print(f"Command failed: {e}")
except SandboxNotFoundException:
    print("Sandbox no longer exists")
except SandboxException as e:
    print(f"Sandbox error: {e}")
```

## Models

### SandboxState
- `INITIALIZING` - Sandbox initializing
- `RUNNING` - Sandbox running
- `PAUSED` - Sandbox paused
- `STOPPED` - Sandbox stopped
- `ERROR` - Sandbox error

### SandboxInfo
```python
info = sandbox.info()
print(info.sandbox_id)
print(info.state)  # SandboxState
print(info.created_at)
print(info.updated_at)
print(info.metadata)  # Dict
```

### CommandResult
```python
result = sandbox.commands.run("echo 'test'")
print(result.exit_code)  # int
print(result.stdout)     # str
print(result.stderr)     # str
print(result.pid)        # int
```

### ProcessInfo
```python
processes = sandbox.commands.list()
for proc in processes:
    print(proc.pid)      # int
    print(proc.cmd)      # str
    print(proc.args)     # List[str]
    print(proc.cwd)      # str
    print(proc.envs)     # Dict[str, str]
```

### FilesystemEntry
```python
entries = sandbox.files.list("/tmp")
for entry in entries:
    print(entry.path)         # str
    print(entry.name)         # str
    print(entry.type)         # EntryType (FILE/DIRECTORY/SYMLINK)
    print(entry.size)         # int
    print(entry.mode)         # int
    print(entry.modified_at)  # Optional[str]
```

### SandboxMetrics
```python
metrics = sandbox.metrics()
print(metrics.cpu_usage_percent)      # float
print(metrics.memory_usage_bytes)     # int
print(metrics.disk_usage_bytes)       # int
print(metrics.uptime_seconds)         # int
```

## Advanced Examples

### Running Python Code

```python
code = """
import json
data = {'hello': 'world'}
print(json.dumps(data))
"""

result = sandbox.commands.run(
    f"python3 -c \"{code}\"",
    timeout=30
)
print(result.stdout)
```

### Concurrent Operations (Async)

```python
import asyncio
from my_sdk import AsyncSandbox

async def run_tests():
    sandbox = await AsyncSandbox.create(api_url="http://localhost:8000")
    
    # Run multiple tests concurrently
    results = await asyncio.gather(
        sandbox.commands.run("pytest test_1.py"),
        sandbox.commands.run("pytest test_2.py"),
        sandbox.commands.run("pytest test_3.py"),
    )
    
    for i, result in enumerate(results):
        print(f"Test {i+1}: {'PASS' if result.exit_code == 0 else 'FAIL'}")
    
    await sandbox.kill()

asyncio.run(run_tests())
```

### File Transfer

```python
# Upload and run script
sandbox.files.upload("train.py", "/tmp/train.py")

result = sandbox.commands.run(
    "python /tmp/train.py --epochs 10"
)

# Download results
sandbox.files.download("/tmp/model.pkl", "./model.pkl")
```

## Architecture

```
my_sdk/
├── __init__.py              # Public API exports
├── exceptions.py            # Exception classes
├── models.py                # Data models
├── config.py                # Configuration
├── api/
│   ├── __init__.py         # Base API client
│   ├── sync.py             # Synchronous HTTP client
│   └── async_client.py     # Asynchronous HTTP client
├── sync/
│   ├── __init__.py
│   ├── sandbox.py          # Sync Sandbox class
│   ├── commands.py         # Sync Commands class
│   └── filesystem.py       # Sync Filesystem class
└── async_sdk/
    ├── __init__.py
    ├── sandbox.py          # Async Sandbox class
    ├── commands.py         # Async Commands class
    └── filesystem.py       # Async Filesystem class
```

## Compatibility

- **Python**: 3.7+
- **Dependencies**: None (uses stdlib only)
- **OS**: Linux, macOS, Windows

## Future Enhancements

- [ ] Git operations support
- [ ] PTY/Terminal support
- [ ] Snapshots and templates
- [ ] Volume/Persistent storage
- [ ] Network configuration
- [ ] Event streaming
- [ ] Better error messages
- [ ] Connection pooling
- [ ] Retry logic
- [ ] Rate limiting

## License

MIT

## Contributing

Contributions welcome! Please ensure:
- Code is properly typed
- Tests pass
- Documentation is updated
- Examples work correctly
