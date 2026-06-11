# Deployment & Production Guide

## Overview

This guide helps you set up and deploy your My Sandbox SDK infrastructure to production.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Client Applications                       │
│  (Using My Sandbox SDK: Sandbox.create(), etc.)            │
└────────────────────┬────────────────────────────────────────┘
                     │ REST API Calls (HTTP/HTTPS)
                     ↓
┌─────────────────────────────────────────────────────────────┐
│              API Server (Your Implementation)               │
│  • FastAPI / Express / Django / Flask                      │
│  • Handles: Create, Run, Kill, Files                       │
│  • Authentication: API Keys / OAuth                        │
│  • Logging & Monitoring                                   │
└────────────┬──────────────────────────────┬─────────────────┘
             │                              │
       Docker/K8s              Custom Infrastructure
             │                              │
      ┌──────▼──────────┐          ┌──────▼──────────┐
      │   Containers    │          │  VMs / Hardware  │
      │  (Sandboxes)    │          │  (Sandboxes)     │
      └─────────────────┘          └──────────────────┘
```

## Option 1: Docker + FastAPI (Recommended for Quick Start)

### 1.1 Create API Server (Python)

```bash
mkdir sandbox-api
cd sandbox-api
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install fastapi uvicorn docker python-dotenv
```

Create `main.py`:

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import docker
import uuid
from datetime import datetime

app = FastAPI(title="My Sandbox API")
docker_client = docker.from_env()
sandboxes: Dict[str, dict] = {}

class CreateSandboxRequest(BaseModel):
    template_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class RunCommandRequest(BaseModel):
    command: str
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    timeout: Optional[float] = None

@app.post("/sandboxes")
async def create_sandbox(request: CreateSandboxRequest):
    """Create new sandbox"""
    try:
        container = docker_client.containers.run(
            "python:3.11",
            "/bin/bash",
            detach=True,
            stdin_open=True,
            tty=True,
            name=f"sandbox-{uuid.uuid4().hex[:8]}",
        )
        
        sandbox_id = f"sb-{uuid.uuid4().hex}"
        sandboxes[sandbox_id] = {
            "container": container,
            "created_at": datetime.now().isoformat(),
        }
        
        return {
            "sandbox_id": sandbox_id,
            "state": "running",
            "created_at": sandboxes[sandbox_id]["created_at"],
            "updated_at": datetime.now().isoformat(),
            "metadata": request.metadata or {}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sandboxes/{sandbox_id}")
async def get_sandbox(sandbox_id: str):
    """Get sandbox info"""
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    sandbox = sandboxes[sandbox_id]
    container = sandbox["container"]
    
    return {
        "sandbox_id": sandbox_id,
        "state": "running" if container.status == "running" else "stopped",
        "created_at": sandbox["created_at"],
        "updated_at": datetime.now().isoformat(),
    }

@app.post("/sandboxes/{sandbox_id}/commands/run")
async def run_command(sandbox_id: str, request: RunCommandRequest):
    """Run command in sandbox"""
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    try:
        container = sandboxes[sandbox_id]["container"]
        
        result = container.exec_run(
            cmd=request.command,
            workdir=request.cwd or "/",
            environment=request.env or {},
            timeout=request.timeout or 30,
        )
        
        return {
            "exit_code": result.exit_code,
            "stdout": result.output.decode("utf-8") if result.output else "",
            "stderr": "",
            "pid": 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sandboxes/{sandbox_id}/kill")
async def kill_sandbox(sandbox_id: str):
    """Kill sandbox"""
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    try:
        container = sandboxes[sandbox_id]["container"]
        container.kill()
        del sandboxes[sandbox_id]
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sandboxes/{sandbox_id}/files")
async def list_files(sandbox_id: str, path: str = "/"):
    """List directory contents"""
    if sandbox_id not in sandboxes:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    try:
        container = sandboxes[sandbox_id]["container"]
        result = container.exec_run(f"ls -la {path}")
        # Parse output and return entries...
        return {"entries": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ... add more endpoints

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### 1.2 Run Locally

```bash
python main.py
```

Then test with SDK:
```python
from my_sdk import Sandbox

sandbox = Sandbox.create(api_url="http://localhost:8000")
result = sandbox.commands.run("echo 'hello'")
print(result.stdout)
sandbox.kill()
```

### 1.3 Docker Deployment

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install Docker CLI
RUN apt-get update && apt-get install -y docker.io && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:
```bash
docker build -t sandbox-api .
docker run -d \
  -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  sandbox-api
```

## Option 2: Kubernetes Deployment

### 2.1 Create Helm Chart

```bash
helm create sandbox-api-chart
```

Create `values.yaml`:

```yaml
replicaCount: 3

image:
  repository: your-registry/sandbox-api
  tag: "1.0.0"
  pullPolicy: IfNotPresent

service:
  type: LoadBalancer
  port: 8000

resources:
  limits:
    memory: "512Mi"
    cpu: "500m"
  requests:
    memory: "256Mi"
    cpu: "250m"

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 80
```

Deploy:
```bash
helm install sandbox-api ./sandbox-api-chart
```

### 2.2 Configure Sandboxes

Use Docker-in-Docker or socket mount for container management:

```yaml
containers:
- name: sandbox-api
  image: sandbox-api:1.0.0
  volumeMounts:
  - name: docker-sock
    mountPath: /var/run/docker.sock
volumes:
- name: docker-sock
  hostPath:
    path: /var/run/docker.sock
```

## Option 3: AWS Deployment

### 3.1 Using ECS + Fargate

Create task definition:

```json
{
  "family": "sandbox-api",
  "containerDefinitions": [
    {
      "name": "sandbox-api",
      "image": "your-account.dkr.ecr.us-east-1.amazonaws.com/sandbox-api:latest",
      "portMappings": [{"containerPort": 8000}],
      "environment": [
        {"name": "API_KEY", "value": "your-secret-key"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/sandbox-api",
          "awslogs-region": "us-east-1"
        }
      }
    }
  ],
  "requiresCompatibilities": ["FARGATE"],
  "networkMode": "awsvpc",
  "cpu": "512",
  "memory": "1024"
}
```

Register and deploy:
```bash
aws ecs register-task-definition --cli-input-json file://task-def.json
aws ecs create-service --cluster sandbox --task-definition sandbox-api --desired-count 3 --launch-type FARGATE
```

## Production Checklist

### Security
- [ ] Enable HTTPS/TLS
- [ ] Implement API key authentication
- [ ] Add rate limiting
- [ ] Validate all inputs
- [ ] Use secrets manager for credentials
- [ ] Implement CORS properly

### Monitoring
- [ ] Add logging (CloudWatch, ELK, etc.)
- [ ] Add metrics (Prometheus, DataDog, etc.)
- [ ] Set up alerting
- [ ] Monitor API latency
- [ ] Monitor sandbox resource usage

### Resilience
- [ ] Implement retry logic
- [ ] Add load balancing
- [ ] Configure auto-scaling
- [ ] Add health checks
- [ ] Implement graceful shutdown
- [ ] Add circuit breakers

### Performance
- [ ] Use connection pooling
- [ ] Add caching where appropriate
- [ ] Profile bottlenecks
- [ ] Optimize Docker image size
- [ ] Use Alpine Linux for base images

### Operations
- [ ] Document deployment process
- [ ] Create runbooks
- [ ] Set up CI/CD pipeline
- [ ] Implement blue-green deployment
- [ ] Create backup/restore procedures
- [ ] Plan for disaster recovery

## Example nginx Configuration

```nginx
upstream sandbox_api {
    server 127.0.0.1:8000;
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
}

server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://sandbox_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts for long-running operations
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }

    # Rate limiting
    location /sandboxes {
        limit_req zone=api_limit burst=10 nodelay;
        proxy_pass http://sandbox_api;
    }
}

# Define rate limit zone
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
```

## Monitoring Example (Prometheus)

```python
from prometheus_client import Counter, Histogram

# Metrics
sandbox_created = Counter('sandbox_created_total', 'Total sandboxes created')
command_execution_time = Histogram('command_execution_seconds', 'Command execution time')

@app.post("/sandboxes")
async def create_sandbox(request: CreateSandboxRequest):
    sandbox_created.inc()
    # ... implementation
```

## Logging Example

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.post("/sandboxes/{sandbox_id}/commands/run")
async def run_command(sandbox_id: str, request: RunCommandRequest):
    logger.info(f"Running command in {sandbox_id}: {request.command}")
    try:
        # ... implementation
    except Exception as e:
        logger.error(f"Command failed: {e}")
        raise
```

## Cost Optimization

1. **Container Pooling**: Pre-warm containers
2. **Resource Limits**: Prevent runaway processes
3. **Auto-scaling**: Scale down during low traffic
4. **Spot Instances**: Use for non-critical tasks
5. **Reserved Capacity**: For baseline load

## Scaling Considerations

```
Single Server (Dev): 1 API + 10 sandboxes
Small Scale: 2-3 APIs + 50-100 sandboxes
Medium Scale: 5-10 APIs + 100-500 sandboxes (K8s)
Large Scale: 20+ APIs + 1000+ sandboxes (K8s + custom)
```

## Testing Production

```python
import asyncio
from my_sdk import AsyncSandbox

async def load_test():
    tasks = []
    for i in range(100):
        task = AsyncSandbox.create(api_url="https://api.example.com")
        tasks.append(task)
    
    sandboxes = await asyncio.gather(*tasks)
    
    # Run commands
    results = await asyncio.gather(*[
        sb.commands.run("echo 'test'")
        for sb in sandboxes
    ])
    
    # Cleanup
    await asyncio.gather(*[
        sb.kill()
        for sb in sandboxes
    ])
    
    print(f"Completed {len(results)} operations successfully")

asyncio.run(load_test())
```

## Troubleshooting

### High API Latency
- Check network between client and server
- Monitor server CPU/memory
- Check database/storage performance
- Increase timeout values in SDK

### Sandboxes Not Starting
- Check Docker/container availability
- Verify resource limits
- Check logs for errors
- Increase retry count

### Failed Commands
- Check command syntax
- Verify environment variables
- Check working directory exists
- Review stdout/stderr for errors

## Support

For deployment help:
1. Check application logs
2. Review API_SERVER_GUIDE.md
3. Run diagnostics
4. Monitor metrics

---

**Ready for production!** 🚀
