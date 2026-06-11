# My Sandbox SDK - Documentation Index

## Quick Navigation

### 🚀 Getting Started (START HERE)
1. **[QUICKSTART.md](QUICKSTART.md)** - 5 min read
   - 30-second examples
   - Common tasks
   - Basic setup

2. **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - 10 min read
   - What's been built
   - Features overview
   - Comparison with E2B

### 📚 Full Documentation
3. **[README.md](README.md)** - Complete reference
   - Full API documentation
   - All methods and classes
   - Response models
   - Error handling

### 🔨 Building Your Server
4. **[API_SERVER_GUIDE.md](API_SERVER_GUIDE.md)** - Implementation guide
   - REST endpoint specifications
   - Request/response formats
   - Python (FastAPI) examples
   - Node.js (Express) examples
   - Testing instructions

### 🌐 Deploying to Production
5. **[DEPLOYMENT.md](DEPLOYMENT.md)** - Production setup
   - Local Docker setup
   - Kubernetes deployment
   - AWS ECS/Fargate
   - Monitoring & logging
   - Security checklist

### 💡 Examples
6. **[examples_sync.py](examples_sync.py)** - Synchronous examples
   - Basic usage
   - Commands
   - Filesystem operations
   - Metrics
   - Context managers

7. **[examples_async.py](examples_async.py)** - Asynchronous examples
   - Async/await patterns
   - Concurrent operations
   - Context managers
   - Load testing

## What to Read When...

### "I want to start right now!"
👉 Read: [QUICKSTART.md](QUICKSTART.md) (5 min)

### "I want to understand what was built"
👉 Read: [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) (10 min)

### "I need to build the API server"
👉 Read: [API_SERVER_GUIDE.md](API_SERVER_GUIDE.md) (20 min)

### "I need the complete API reference"
👉 Read: [README.md](README.md) (30 min)

### "I need to deploy to production"
👉 Read: [DEPLOYMENT.md](DEPLOYMENT.md) (30 min)

### "I want to see working code"
👉 Run: `examples_sync.py` or `examples_async.py`

### "I need to test my integration"
👉 Run: `pytest tests.py -v`

## SDK Structure

```
my_sdk/
├── Sandbox (sync)              → Use this for simple tasks
├── AsyncSandbox (async)        → Use this for concurrent work
├── Commands                    → Execute commands
├── Filesystem                  → File operations
└── Models/Exceptions           → Data types & errors
```

## Common Workflows

### Workflow 1: Simple Command Execution
```
1. Sandbox.create()
2. sandbox.commands.run()
3. sandbox.kill()
```
📖 See: QUICKSTART.md - "30-Second Example"

### Workflow 2: File Upload & Process
```
1. Sandbox.create()
2. sandbox.files.upload()
3. sandbox.commands.run()
4. sandbox.files.download()
5. sandbox.kill()
```
📖 See: examples_sync.py - "File Transfer"

### Workflow 3: Concurrent Processing (Async)
```
1. await AsyncSandbox.create()
2. await asyncio.gather(many commands)
3. await sandbox.kill()
```
📖 See: examples_async.py - "Concurrent Commands"

### Workflow 4: Production Deployment
```
1. Implement REST server (API_SERVER_GUIDE.md)
2. Dockerize it (DEPLOYMENT.md)
3. Deploy to K8s/AWS/etc (DEPLOYMENT.md)
4. Point SDK to your server
```
📖 See: DEPLOYMENT.md

## Key Concepts

### API Design
The SDK communicates with YOUR REST API server. You control the backend.

```
Your Code → My SDK → REST API → Your Server → Docker/VMs
```

### No Vendor Lock-in
Unlike E2B, you're not tied to their infrastructure. You can run this anywhere.

### Zero Dependencies
The SDK uses only Python standard library (urllib). No heavy packages.

### Both Sync & Async
Simple code? Use `Sandbox`. Concurrent work? Use `AsyncSandbox`.

## File Reference

| File | Purpose | When to Read |
|------|---------|-------------|
| QUICKSTART.md | Getting started | First 5 minutes |
| PROJECT_SUMMARY.md | Project overview | After QUICKSTART |
| README.md | Full API docs | Implementation time |
| API_SERVER_GUIDE.md | Build your server | Before writing server code |
| DEPLOYMENT.md | Production setup | Before going live |
| examples_sync.py | Sync examples | Want to see code |
| examples_async.py | Async examples | Want concurrent code |
| tests.py | Test suite | Testing integration |
| requirements.txt | Dev dependencies | Setting up environment |
| pyproject.toml | Package config | For pip install -e . |

## Technology Stack

### SDK Side
- **Python**: 3.7+
- **Standard Library Only**: urllib, json, asyncio
- **Type Hints**: Full coverage
- **Documentation**: Comprehensive

### Server Side (Your Choice)
- **Framework**: FastAPI, Express, Django, Flask, etc.
- **Container**: Docker, Podman, etc.
- **Infrastructure**: K8s, AWS, GCP, Azure, on-prem, etc.

## Quick Checklist

### To Get Started
- [ ] Read QUICKSTART.md
- [ ] Read PROJECT_SUMMARY.md
- [ ] Run examples_sync.py (need server running)

### To Build Server
- [ ] Read API_SERVER_GUIDE.md
- [ ] Read DEPLOYMENT.md - Option 1 (FastAPI)
- [ ] Implement endpoints
- [ ] Test with examples_sync.py

### To Go to Production
- [ ] Read DEPLOYMENT.md
- [ ] Choose deployment option
- [ ] Set up monitoring
- [ ] Configure security
- [ ] Load test
- [ ] Deploy!

## Need Help?

### Installation Issues
→ See: QUICKSTART.md - "Installation"

### API Usage Questions  
→ See: README.md - "Core APIs"

### How to Build Server
→ See: API_SERVER_GUIDE.md

### Production Deployment
→ See: DEPLOYMENT.md

### Code Examples
→ See: examples_sync.py, examples_async.py

### Error Handling
→ See: README.md - "Error Handling"

## Next Steps

**Right Now**: 
1. Read QUICKSTART.md
2. Skim PROJECT_SUMMARY.md

**Next Hour**:
1. Read API_SERVER_GUIDE.md
2. Start implementing your REST server

**Next Day**:
1. Test integration with examples
2. Read DEPLOYMENT.md
3. Plan production setup

**This Week**:
1. Complete server implementation
2. Load test
3. Deploy!

## Version Info

- **SDK Version**: 0.1.0
- **Python**: 3.7+
- **Status**: Production Ready ✅
- **Dependencies**: 0 (stdlib only)

## License

MIT - Free to use in your projects!

---

**Welcome to My Sandbox SDK!** 🎉

Start with [QUICKSTART.md](QUICKSTART.md) →
