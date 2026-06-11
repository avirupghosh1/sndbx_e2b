# Deep agent web UI

Small **FastAPI** app + static page that sends your task to the same **Deep Agents + `SandboxDeepAgentBackend`** stack as `examples/deepagents_my_sandbox.py`, and streams **LangGraph `stream_events` v2** (tool starts/ends, model stream chunks) over **SSE**.

## Prerequisites

1. Sandbox API running (`api_server` docker compose or `python main.py`).
2. **LLM:** either ``OPENROUTER_API_KEY`` **or** local Ollama (``USE_OLLAMA=1``; see ``../deepagents_my_sandbox.py``).
3. Python deps:

```bash
cd /path/to/intern_1strepo
pip install "my-sandbox-sdk[deepagents]" -r examples/deepagent_ui/requirements.txt

export OPENROUTER_API_KEY=sk-or-v1-...
# Or Ollama: export USE_OLLAMA=1 OLLAMA_MODEL=llama3.2
export MY_SANDBOX_API_URL=http://127.0.0.1:8000
export MY_SANDBOX_API_KEY=test-key-12345

# From repo root (PYTHONPATH so ``examples.*`` resolves):
PYTHONPATH=. uvicorn examples.deepagent_ui.server:app --host 127.0.0.1 --port 8765
```

Open **http://127.0.0.1:8765/**

Alternative (no PYTHONPATH): ``cd examples/deepagent_ui && python -m uvicorn server:app --host 127.0.0.1 --port 8765``

## Notes

- **One run at a time** (server lock). Wait for the previous run to finish (sandbox killed) before starting another.
- First **Sandbox.create** can take **minutes** while Docker pulls `python:3.11`; the log will show a status line then `sandbox_id` when ready.
- Streams **`stream_events(version="v3")`** as a **GraphRunStream**: the UI consumes **`messages`** + **`values`** projections (via `interleave` when both exist), so you see model stream chunks and state snapshots (including tool **ToolMessage**s in `messages_tail` on `values`). A final **`kind: final`** line includes the last messages from `run.output`.
