# My Sandbox SDK - Quick Start Guide

## Installation

```bash
cd my_sandbox_sdk
pip install -e .
```

Or just copy `my_sdk` folder to your project and import directly.

## 30-Second Example

### Synchronous

```python
from my_sdk import Sandbox

# Create sandbox
sandbox = Sandbox.create(api_url="http://localhost:8000")

# Run command
result = sandbox.commands.run("echo 'Hello World'")
print(result.stdout)  # "Hello World"

# Cleanup
sandbox.kill()
```

### Asynchronous

```python
import asyncio
from my_sdk import AsyncSandbox

async def main():
    sandbox = await AsyncSandbox.create(api_url="http://localhost:8000")
    result = await sandbox.commands.run("echo 'Hello World'")
    print(result.stdout)  # "Hello World"
    await sandbox.kill()

asyncio.run(main())
```

## Common Tasks

### 1. File Operations

```python
sandbox = Sandbox.create(api_url="http://localhost:8000")

# Write file
sandbox.files.write("/tmp/hello.txt", "Hello World")

# Read file
content = sandbox.files.read("/tmp/hello.txt")
print(content)  # "Hello World"

# List directory
entries = sandbox.files.list("/tmp")
for entry in entries:
    print(entry.name, entry.type)

# Delete file
sandbox.files.delete("/tmp/hello.txt")

sandbox.kill()
```

### 2. Process Management

```python
sandbox = Sandbox.create(api_url="http://localhost:8000")

# Run Python script
result = sandbox.commands.run("python3 -c \"print('hello')\"")
print(result.stdout)

# List running processes
processes = sandbox.commands.list()
for proc in processes:
    print(f"PID {proc.pid}: {proc.cmd}")

# Kill specific process
sandbox.commands.kill(pid=1234)

sandbox.kill()
```

### 3. Environment Variables

```python
sandbox = Sandbox.create(api_url="http://localhost:8000")

result = sandbox.commands.run(
    "echo $MY_VAR",
    env={"MY_VAR": "My Value"}
)
print(result.stdout)  # "My Value"

sandbox.kill()
```

### 4. Working Directory

```python
sandbox = Sandbox.create(api_url="http://localhost:8000")

result = sandbox.commands.run(
    "pwd",
    cwd="/tmp"
)
print(result.stdout)  # "/tmp"

sandbox.kill()
```

### 5. Context Manager (Auto-Cleanup)

```python
with Sandbox.create(api_url="http://localhost:8000") as sandbox:
    result = sandbox.commands.run("ls")
    print(result.stdout)
# Sandbox automatically cleaned up!
```

## Configuration

### Via Environment Variables

```bash
export MY_SDK_API_URL="http://localhost:8000"
export MY_SDK_API_KEY="your-api-key"
export MY_SDK_REQUEST_TIMEOUT="30"
```

Then use default values:
```python
from my_sdk.config import get_default_config

config = get_default_config()
sandbox = Sandbox.create(
    api_url=config.api_url,
    api_key=config.api_key,
)
```

### Via Arguments

```python
sandbox = Sandbox.create(
    api_url="http://localhost:8000",
    api_key="your-api-key",
    request_timeout=60
)
```

## Error Handling

```python
from my_sdk import (
    Sandbox,
    SandboxException,
    SandboxNotFoundException,
    TimeoutException,
    FileNotFoundException,
)

try:
    sandbox = Sandbox.create(api_url="http://localhost:8000")
    result = sandbox.commands.run("sleep 100", timeout=5)
except TimeoutException:
    print("Command timed out!")
except FileNotFoundException:
    print("File not found!")
except SandboxNotFoundException:
    print("Sandbox no longer exists!")
except SandboxException as e:
    print(f"Error: {e}")
finally:
    try:
        sandbox.kill()
    except:
        pass
```

## Running Tests

```bash
# Run pytest
pytest tests.py -v

# Run async tests
pytest tests.py -v -m asyncio

# Run manual test
python tests.py
```

## Examples

See `examples_sync.py` and `examples_async.py` for complete examples:

```bash
python examples_sync.py
python examples_async.py
```

## API Server Setup

### Option 1: Python (FastAPI)

```python
from fastapi import FastAPI
import docker
import uuid

app = FastAPI()
client = docker.from_env()
sandboxes = {}

@app.post("/sandboxes")
async def create_sandbox():
    container = client.containers.run(
        "python:3.11",
        "/bin/bash",
        detach=True,
        stdin_open=True,
        tty=True,
    )
    sandbox_id = f"sb-{uuid.uuid4().hex[:8]}"
    sandboxes[sandbox_id] = container
    return {
        "sandbox_id": sandbox_id,
        "state": "running",
        "created_at": "2024-01-15T10:00:00Z",
        "updated_at": "2024-01-15T10:00:00Z",
    }

@app.post("/sandboxes/{sandbox_id}/kill")
async def kill_sandbox(sandbox_id: str):
    container = sandboxes[sandbox_id]
    container.kill()
    del sandboxes[sandbox_id]
    return {"success": True}

# ... more endpoints
```

### Option 2: Node.js (Express)

```javascript
const express = require('express');
const Docker = require('dockerode');

const app = express();
const docker = new Docker();
const sandboxes = {};

app.post('/sandboxes', async (req, res) => {
  const container = await docker.createContainer({
    Image: 'python:3.11',
    Cmd: ['/bin/bash'],
    OpenStdin: true,
    Tty: true,
  });
  
  await container.start();
  
  const sandboxId = `sb-${Math.random().toString(36).substr(2, 8)}`;
  sandboxes[sandboxId] = container;
  
  res.json({
    sandbox_id: sandboxId,
    state: 'running',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  });
});

// ... more endpoints
```

See `API_SERVER_GUIDE.md` for full implementation details.

## Next Steps

1. ✅ Install SDK
2. ✅ Set up API server
3. ✅ Create your first sandbox
4. ✅ Run commands
5. ✅ Manage files
6. ✅ Handle errors
7. 🚀 Build your application!

## Troubleshooting

### "Connection refused"
- Make sure API server is running
- Check `api_url` is correct

### "Unauthorized"
- Check API key is correct
- Make sure server requires authentication

### "Command timeout"
- Increase `request_timeout` parameter
- Check if command is stuck in infinite loop

### "File not found"
- Verify file path is correct
- Make sure it's using absolute paths

## Architecture Overview

```
Your App
    ↓
My SDK (Python)
    ↓
REST API (Your server)
    ↓
Docker/VMs/Containers
    ↓
Sandbox Environment
```

## Support & Resources

- **README.md** - Full API documentation
- **API_SERVER_GUIDE.md** - How to build the server
- **examples_sync.py** - Synchronous examples
- **examples_async.py** - Asynchronous examples
- **tests.py** - Test suite

## License

MIT - Use freely in your projects!
