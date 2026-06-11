#!/usr/bin/env python3
"""
Minimal web UI server: task box + SSE stream of LangGraph events (tools, model chunks).

Run from repository root::

  # LLM: OpenRouter (default) **or** local Ollama — same env as ``deepagents_my_sandbox.py``:
  export OPENROUTER_API_KEY=sk-or-v1-...
  # export USE_OLLAMA=1
  # export OLLAMA_MODEL=llama3.2

  export MY_SANDBOX_API_URL=http://127.0.0.1:8000
  export MY_SANDBOX_API_KEY=test-key-12345
  pip install "my-sandbox-sdk[deepagents]" -r examples/deepagent_ui/requirements.txt
  uvicorn examples.deepagent_ui.server:app --host 127.0.0.1 --port 8765 --reload

Open http://127.0.0.1:8765/

Uses LangGraph ``stream_events(version='v3')``, which returns a **GraphRunStream** (iterate
``messages`` / ``values`` via ``interleave``, not v2-style ``on_tool_start`` dicts). Falls back to
``stream_mode='updates'`` if v3 consumption fails.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Iterator

# Repo layout: intern_1strepo/examples/deepagent_ui/server.py
_UI_DIR = Path(__file__).resolve().parent
_EXAMPLES = _UI_DIR.parent
_ROOT = _EXAMPLES.parent
sys.path.insert(0, str(_ROOT / "my_sandbox_sdk"))
sys.path.insert(0, str(_EXAMPLES))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from langchain_core.messages import HumanMessage  # noqa: E402

import deepagents_my_sandbox as demo  # noqa: E402
from langgraph.errors import GraphRecursionError  # noqa: E402

RUN_LOCK = threading.Lock()
logger = logging.getLogger("deepagent_ui")


def _json_default(o: Any) -> Any:
    if hasattr(o, "model_dump"):
        try:
            return o.model_dump()
        except Exception:
            pass
    if hasattr(o, "dict"):
        try:
            return o.dict()
        except Exception:
            pass
    s = str(o)
    return s if len(s) <= 6000 else s[:6000] + "…"


def _summarize_v3_stream_item(projection: str, item: Any) -> dict[str, Any]:
    """JSON-friendly summary for LangGraph v3 ``messages`` / ``values`` projections."""
    out: dict[str, Any] = {"projection": projection}
    if projection == "values" and isinstance(item, dict):
        msgs = item.get("messages")
        if isinstance(msgs, list) and msgs:
            out["messages_tail"] = _json_default(msgs[-8:])
        else:
            out["state_keys"] = list(item.keys())[:40]
        return out
    out["item"] = _json_default(item)
    return out


def _iter_langgraph_v3_sse(run: Any) -> Iterator[str]:
    """Drive ``GraphRunStream`` from ``stream_events(..., version='v3')`` → SSE lines."""
    ext = getattr(run, "extensions", None) or {}
    names = [n for n in ("messages", "values") if n in ext]
    if len(names) >= 2:
        for name, item in run.interleave("messages", "values"):
            payload = _summarize_v3_stream_item(name, item)
            yield f"data: {json.dumps({'kind': 'stream', 'payload': payload}, default=_json_default)}\n\n"
        return
    if len(names) == 1:
        n = names[0]
        ch = getattr(run, n)
        for item in ch:
            payload = _summarize_v3_stream_item(n, item)
            yield f"data: {json.dumps({'kind': 'stream', 'payload': payload}, default=_json_default)}\n\n"
        return
    for ev in run:
        if not isinstance(ev, dict) or ev.get("type") != "event":
            continue
        mth = ev.get("method")
        params = ev.get("params") or {}
        data = params.get("data")
        yield f"data: {json.dumps({'kind': 'protocol', 'method': mth, 'payload': _json_default(data)}, default=_json_default)}\n\n"
class ChatBody(BaseModel):
    task: str = Field(..., min_length=1, max_length=200_000)


app = FastAPI(title="Deep agent sandbox UI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/chat/stream")
def chat_stream(body: ChatBody) -> StreamingResponse:
    task = body.task.strip()

    def gen() -> Iterator[str]:
        if not RUN_LOCK.acquire(blocking=False):
            yield f"data: {json.dumps({'kind': 'error', 'message': 'Another task is still running.'})}\n\n"
            return
        sb = None
        try:
            yield f"data: {json.dumps({'kind': 'status', 'message': 'Creating sandbox + agent (first pull can take minutes)…'})}\n\n"
            agent, sb, rlim = demo.build_deep_agent_session()
            yield f"data: {json.dumps({'kind': 'sandbox', 'sandbox_id': sb.sandbox_id, 'recursion_limit': rlim})}\n\n"

            inp: dict[str, Any] = {"messages": [HumanMessage(content=task)]}
            cfg: dict[str, Any] = {"recursion_limit": rlim}

            stream_events = getattr(agent, "stream_events", None)
            used_stream_events = False
            # LangGraph v3: stream_events returns GraphRunStream — iterate messages/values, not v2 event dicts.
            if callable(stream_events):
                try:
                    run = stream_events(inp, config=cfg, version="v3")
                    yield from _iter_langgraph_v3_sse(run)
                    try:
                        final = run.output
                        if isinstance(final, dict) and final.get("messages"):
                            yield f"data: {json.dumps({'kind': 'final', 'messages_tail': _json_default(final['messages'][-12:])}, default=_json_default)}\n\n"
                    except Exception:
                        logger.debug("run.output after v3 stream", exc_info=True)
                    used_stream_events = True
                except GraphRecursionError as e:
                    yield f"data: {json.dumps({'kind': 'error', 'message': f'recursion_limit: {e!s}'})}\n\n"
                    used_stream_events = True
                except Exception as stream_ex:
                    logger.warning("stream_events(v3) failed: %s", stream_ex)
            if not used_stream_events:
                yield f"data: {json.dumps({'kind': 'status', 'message': 'Using stream_mode=updates'})}\n\n"
                try:
                    for chunk in agent.stream(inp, config=cfg, stream_mode="updates"):
                        yield f"data: {json.dumps({'kind': 'update', 'payload': _json_default(chunk)}, default=_json_default)}\n\n"
                except GraphRecursionError as e:
                    yield f"data: {json.dumps({'kind': 'error', 'message': f'recursion_limit: {e!s}'})}\n\n"

            yield f"data: {json.dumps({'kind': 'done'})}\n\n"
        except Exception as e:
            logger.exception("run failed")
            yield f"data: {json.dumps({'kind': 'error', 'message': str(e)})}\n\n"
        finally:
            if sb is not None:
                try:
                    sb.kill()
                except Exception:
                    logger.exception("sandbox kill")
            RUN_LOCK.release()

    return StreamingResponse(gen(), media_type="text/event-stream")


_STATIC = _UI_DIR / "static"
if _STATIC.is_dir():
    app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")
