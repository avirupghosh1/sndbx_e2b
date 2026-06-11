# API Server Implementation Guide

This document describes how to implement the REST API server that the Python SDK communicates with.

## Server Requirements

The server should:
1. Accept REST API calls
2. Manage sandbox instances (can be VMs or containers)
3. Execute commands within sandboxes
4. Handle file operations
5. Return JSON responses

## API Endpoints

### Authentication
All requests should include authentication (must match what `api_server` validates):
```
X-API-Key: {api_key}
```

### Sandbox Endpoints

#### 1. Create Sandbox
```
POST /sandboxes
Content-Type: application/json

{
  "template_id": "optional",
  "metadata": {
    "key": "value"
  }
}

Response 201:
{
  "sandbox_id": "sb-abc123def456",
  "state": "initializing",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "metadata": {}
}
```

#### 2. Get Sandbox Info
```
GET /sandboxes/{sandbox_id}

Response 200:
{
  "sandbox_id": "sb-abc123def456",
  "state": "running",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "metadata": {}
}
```

#### 3. Kill Sandbox
```
POST /sandboxes/{sandbox_id}/kill

Response 200:
{
  "success": true,
  "message": "Sandbox killed"
}
```

#### 4. Pause Sandbox
```
POST /sandboxes/{sandbox_id}/pause

Response 200:
{
  "success": true,
  "state": "paused"
}
```

#### 5. Resume Sandbox
```
POST /sandboxes/{sandbox_id}/resume

Response 200:
{
  "success": true,
  "state": "running"
}
```

#### 6. Get Metrics
```
GET /sandboxes/{sandbox_id}/metrics

Response 200:
{
  "cpu_usage_percent": 12.5,
  "memory_usage_bytes": 524288000,
  "disk_usage_bytes": 2147483648,
  "uptime_seconds": 3600
}
```

### Commands Endpoints

#### 1. Run Command
```
POST /sandboxes/{sandbox_id}/commands/run
Content-Type: application/json

{
  "command": "echo 'hello'",
  "cwd": "/tmp",
  "env": {
    "VAR": "value"
  },
  "timeout": 30
}

Response 200:
{
  "exit_code": 0,
  "stdout": "hello\n",
  "stderr": "",
  "pid": 1234
}
```

#### 2. List Processes
```
GET /sandboxes/{sandbox_id}/commands

Response 200:
{
  "processes": [
    {
      "pid": 1234,
      "cmd": "bash",
      "args": ["-i"],
      "cwd": "/home/user",
      "envs": {
        "PATH": "/usr/bin",
        "HOME": "/home/user"
      }
    }
  ]
}
```

#### 3. Kill Process
```
POST /sandboxes/{sandbox_id}/commands/{pid}/kill

Response 200:
{
  "success": true,
  "pid": 1234
}
```

### Filesystem Endpoints

#### 1. List Directory
```
GET /sandboxes/{sandbox_id}/files?path=/tmp

Response 200:
{
  "entries": [
    {
      "path": "/tmp/file.txt",
      "name": "file.txt",
      "type": "file",
      "size": 1024,
      "mode": 33188,
      "modified_at": "2024-01-15T10:30:00Z"
    },
    {
      "path": "/tmp/dir",
      "name": "dir",
      "type": "directory",
      "size": 4096,
      "mode": 16877,
      "modified_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

#### 2. Read File
```
GET /sandboxes/{sandbox_id}/files/read?path=/tmp/file.txt

Response 200:
{
  "path": "/tmp/file.txt",
  "content": "file contents here",
  "encoding": "utf-8"
}

Or for binary (base64):
{
  "path": "/tmp/file.bin",
  "content": "aGVsbG8gd29ybGQ=",
  "encoding": "base64"
}
```

#### 3. Write File
```
POST /sandboxes/{sandbox_id}/files/write
Content-Type: application/json

{
  "path": "/tmp/file.txt",
  "content": "hello world"
}

Response 200:
{
  "bytes_written": 11,
  "path": "/tmp/file.txt"
}
```

#### 4. Delete File
```
POST /sandboxes/{sandbox_id}/files/delete
Content-Type: application/json

{
  "path": "/tmp/file.txt",
  "recursive": false
}

Response 200:
{
  "success": true,
  "path": "/tmp/file.txt"
}
```

#### 5. Upload File
```
POST /sandboxes/{sandbox_id}/files/upload
Content-Type: application/json

{
  "path": "/tmp/upload.txt",
  "content": "base64_encoded_content_here",
  "encoding": "base64"
}

Response 200:
{
  "bytes_written": 1024,
  "path": "/tmp/upload.txt"
}
```

#### 6. Download File
```
GET /sandboxes/{sandbox_id}/files/download?path=/tmp/file.txt

Response 200:
{
  "path": "/tmp/file.txt",
  "content": "base64_encoded_content_here",
  "encoding": "base64"
}
```

## Error Responses

### 400 Bad Request
```json
{
  "error": "Invalid request parameters",
  "details": "Missing required field: command"
}
```

### 401 Unauthorized
```json
{
  "error": "Unauthorized",
  "details": "Invalid or missing API key"
}
```

### 404 Not Found
```json
{
  "error": "Sandbox not found",
  "sandbox_id": "sb-nonexistent"
}
```

### 408 Request Timeout
```json
{
  "error": "Request timeout",
  "details": "Command execution exceeded timeout"
}
```

### 500 Internal Server Error
```json
{
  "error": "Internal server error",
  "details": "Detailed error message"
}
```

## Implementation Examples

### Python (FastAPI)
```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class CreateSandboxRequest(BaseModel):
    template_id: Optional[str] = None
    metadata: Optional[dict] = None

@app.post("/sandboxes")
async def create_sandbox(request: CreateSandboxRequest):
    # Your implementation here
    sandbox_id = "sb-" + uuid.uuid4().hex
    return {
        "sandbox_id": sandbox_id,
        "state": "initializing",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "metadata": request.metadata or {}
    }

@app.post("/sandboxes/{sandbox_id}/commands/run")
async def run_command(sandbox_id: str, request: RunCommandRequest):
    # Your implementation here
    result = subprocess.run(...)
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "pid": result.pid
    }
```

### Node.js (Express)
```javascript
const express = require('express');
const app = express();
app.use(express.json());

app.post('/sandboxes', async (req, res) => {
  // Your implementation here
  const sandboxId = 'sb-' + Math.random().toString(36).substr(2, 9);
  res.json({
    sandbox_id: sandboxId,
    state: 'initializing',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    metadata: req.body.metadata || {}
  });
});

app.post('/sandboxes/:sandboxId/commands/run', async (req, res) => {
  // Your implementation here
  const { exec } = require('child_process');
  exec(req.body.command, (error, stdout, stderr) => {
    res.json({
      exit_code: error ? error.code : 0,
      stdout: stdout,
      stderr: stderr,
      pid: 0
    });
  });
});
```

## Implementation Considerations

1. **Container/VM Management**: Use Docker, Kubernetes, or other container runtimes to manage sandboxes
2. **Isolation**: Ensure proper isolation between sandboxes
3. **Security**: Implement proper authentication and authorization
4. **Cleanup**: Properly clean up resources when sandboxes are killed
5. **Timeouts**: Implement timeout handling for long-running commands
6. **Logging**: Log all operations for debugging
7. **Concurrency**: Handle multiple concurrent requests
8. **Resource Limits**: Implement CPU, memory, and disk limits per sandbox
9. **State Management**: Track sandbox state properly
10. **File Operations**: Handle binary file upload/download safely

## Testing

Test your API server with:

```bash
# Test create sandbox
curl -X POST http://localhost:8000/sandboxes \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key-12345" \
  -d '{"metadata": {"name": "test"}}'

# Test run command
curl -X POST http://localhost:8000/sandboxes/sb-123/commands/run \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key-12345" \
  -d '{"command": "echo hello"}'

# Test list directory
curl -X GET "http://localhost:8000/sandboxes/sb-123/files?path=/tmp" \
  -H "X-API-Key: test-key-12345"
```

## Next Steps

1. Choose a server framework (FastAPI, Express, etc.)
2. Implement sandbox management (Docker/VM)
3. Implement the REST API endpoints
4. Add proper error handling
5. Add authentication
6. Test with the Python SDK
7. Add metrics collection
8. Deploy to production
