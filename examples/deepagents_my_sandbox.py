#!/usr/bin/env python3
"""
Deep Agents + this project's sandbox API (same pattern as ModalSandbox).

**LLM (pick one)**

1. **OpenRouter** (default) — OpenAI-compatible HTTP with ``langchain_openai.ChatOpenAI``.
   Set ``OPENROUTER_API_KEY``. Default model ``openrouter/free`` (catalog changes often):
   https://openrouter.ai/models?q=free

2. **Ollama (desktop)** — local OpenAI-compatible API. Set ``USE_OLLAMA=1`` and optionally
   ``OLLAMA_MODEL`` (default ``llama3.2``), ``OLLAMA_BASE_URL`` (default ``http://127.0.0.1:11434``).
   Pull the model in the Ollama app first, e.g. ``ollama pull llama3.2``. No OpenRouter key needed.

Some models (including some on OpenRouter) emit a **JSON blob in ``content``** that
*mimics* tool calls instead of using native API ``tool_calls``. The runtime ignores that, so
nothing runs. This script can **coerce** that pattern into real ``tool_calls`` (on by default;
set ``DEEPAGENTS_COERCE_JSON_TOOL_CALLS=0`` to disable). Shapes handled include: a ``tool_calls``
array, a single object with ``action`` / ``name`` / ``type`` (e.g. ``"type": "write_file"``) plus
flat fields (``file_path``, ``content``), hybrids mixing ``arguments`` with duplicate top-level
keys, and OpenAI-style ``function`` blobs. The blob must be **valid JSON** (quoted strings, etc.);
unquoted placeholders in ``content`` will not parse.

Some chat models (especially some OpenRouter free routes) return malformed tool names such as
``execute<|channel|>commentary`` instead of ``execute``. This script wraps the chat model to strip
``<|channel|>…`` suffixes before the agent dispatches tools. Set ``DEEPAGENTS_SANITIZE_TOOL_NAMES=0``
to disable.

This script asks the agent to **build a tiny calculator CLI in the sandbox** (write `/tmp/calc.py`,
run `echo "7 * 6" | python3 /tmp/calc.py`, etc.) and prints a structured **evidence** section
(tool stdout + model steps). Set ``DEEPAGENTS_DUMP_STATE=1`` for a raw state dump.

Why the terminal can look "stuck" with no output
-------------------------------------------------
1. **``Sandbox.create``** calls ``POST /sandboxes``. On the API side, the first container may
   **pull ``python:3.11`` inside that request** — that can take **several minutes** with no
   bytes returned to the client, so this script prints *before* that wait and flushes stdout.
2. **``agent.invoke``** may run **many LLM + tool rounds** with no logging unless you enable
   LangChain logging or prints below.

3. **Open-ended tasks** (e.g. “build a full obfuscator”) can run for a very long time: LangGraph’s
   default ``recursion_limit`` is huge unless you override it. This script sets a **low**
   ``recursion_limit`` by default (see ``DEEPAGENTS_RECURSION_LIMIT``) so runs **stop** instead of
   feeling infinite. Scope your prompt to small, checkable steps.

Prerequisites
-------------
1. Sandbox API running (e.g. ``docker compose`` in ``api_server/``).
2. ``pip install deepagents langchain-openai`` (or ``pip install "my-sandbox-sdk[deepagents]"``).
3. **Either** ``OPENROUTER_API_KEY`` from https://openrouter.ai/keys **or** local Ollama
   (``USE_OLLAMA=1`` + model pulled in the Ollama app).

Run (OpenRouter)::

  export PYTHONUNBUFFERED=1   # optional; helps live logs in some terminals
  export MY_SANDBOX_API_URL=http://127.0.0.1:8000
  export MY_SANDBOX_API_KEY=test-key-12345
  export OPENROUTER_API_KEY=sk-or-v1-...
  # optional — pin a specific free model (ids change; copy from the models page):
  # export OPENROUTER_MODEL=meta-llama/llama-3.2-3b-instruct:free
  # export DEEPAGENTS_DEBUG_LOG=1   # optional LangChain INFO logs
  # export DEEPAGENTS_ALLOW_PARALLEL_TOOL_CALLS=1  # allow parallel tools (default: off = safer for write+run)
  #
  # Why ``write_file`` + ``execute`` can still race (Docker)
  # --------------------------------------------------------
  # ``parallel_tool_calls=False`` only asks the **chat provider** not to batch tools.
  # LangGraph's agent still dispatches **each** pending tool_call as its own ``Send``,
  # so ``execute`` may run **at the same time** as ``write_file``. The SDK backend
  # briefly waits for ``python3 /path/to/file.py`` targets to appear before running
  # the shell command (see ``SandboxDeepAgentBackend``). Set
  # ``MY_SANDBOX_EXECUTE_RACE_WAIT_SEC=0`` on ``SandboxDeepAgentBackend(...)`` via
  # constructor arg ``execute_file_race_wait_sec=0`` if you need to disable that wait.
  # export DEEPAGENTS_RECURSION_LIMIT=40    # max graph steps (default 40); raise only if needed
  # export DEEPAGENTS_USER_PROMPT_FILE=/path/to/prompt.txt   # override the demo user message
  python3 examples/deepagents_my_sandbox.py

Run (Ollama on same machine)::

  export USE_OLLAMA=1
  export OLLAMA_MODEL=llama3.2          # must be pulled in Ollama Desktop
  # export OLLAMA_BASE_URL=http://127.0.0.1:11434   # default
  export MY_SANDBOX_API_URL=http://127.0.0.1:8000
  export MY_SANDBOX_API_KEY=test-key-12345
  python3 examples/deepagents_my_sandbox.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import uuid
from typing import Any, List, Optional, Sequence

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO, "my_sandbox_sdk"))

from deepagents import create_deep_agent  # noqa: E402
from langchain_core.callbacks.manager import (  # noqa: E402
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from pydantic import ConfigDict  # noqa: E402

from langgraph.errors import GraphRecursionError  # noqa: E402

from my_sdk.integrations.deepagents_backend import SandboxDeepAgentBackend  # noqa: E402
from my_sdk.sync.sandbox import Sandbox  # noqa: E402

# Router: OpenRouter picks a live free model for you (best default when single slugs 404).
_DEFAULT_OPENROUTER_MODEL = "openrouter/free"

# Slugs that commonly appear in old tutorials but OpenRouter no longer routes ("No endpoints found").
# https://openrouter.ai/models?q=free — copy a current id if you need a fixed model.
_OPENROUTER_MODEL_ALIASES: dict[str, str] = {
    "mistralai/mistral-7b-instruct": "openrouter/free",
    "mistralai/mistral-7b-instruct:free": "openrouter/free",
    "google/gemma-2-9b-it": "google/gemma-2-9b-it:free",
}


def _log(msg: str) -> None:
    print(msg, flush=True)


def _sanitize_tool_call_name(name: str) -> str:
    if "<|channel|>" in name:
        return name.split("<|channel|>", 1)[0]
    return name


def _tool_call_as_dict(tc: Any) -> dict[str, Any]:
    if isinstance(tc, dict):
        return dict(tc)
    md = getattr(tc, "model_dump", None)
    if callable(md):
        return md()
    return {
        "id": getattr(tc, "id", "") or "",
        "name": getattr(tc, "name", "") or "",
        "args": getattr(tc, "args", {}) or {},
    }


def _env_enabled(var: str, default: str = "1") -> bool:
    return os.environ.get(var, default).strip().lower() not in ("0", "false", "no")


def _sanitize_ai_tool_names(msg: AIMessage) -> AIMessage:
    if not _env_enabled("DEEPAGENTS_SANITIZE_TOOL_NAMES", "1"):
        return msg
    tcs = getattr(msg, "tool_calls", None) or []
    if not tcs:
        return msg
    new_tcs: list[dict[str, Any]] = []
    changed = False
    for tc in tcs:
        d = _tool_call_as_dict(tc)
        n = str(d.get("name") or "")
        fixed = _sanitize_tool_call_name(n)
        if fixed != n:
            d = {**d, "name": fixed}
            changed = True
        new_tcs.append(d)
    if not changed:
        return msg
    if hasattr(msg, "model_copy"):
        return msg.model_copy(update={"tool_calls": new_tcs})
    return msg.copy(update={"tool_calls": new_tcs})


def _extract_json_object_from_text(text: str) -> dict[str, Any] | None:
    """Parse a JSON object possibly wrapped in markdown fences or trailing prose."""
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    for i, ch in enumerate(raw[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    out = json.loads(raw[start : i + 1])
                    return out if isinstance(out, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _parse_tool_arguments_field(value: Any) -> dict[str, Any]:
    """Normalize ``arguments`` / ``args`` which may be a dict or a JSON string (OpenAI API style)."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


_TOOL_PAYLOAD_META: frozenset[str] = frozenset(
    {
        "name",
        "action",
        "tool",
        "id",
        "type",
        "tool_calls",
        "arguments",
        "args",
        "function",
        "role",
    }
)

# If the model puts the tool name in ``type``, ignore JSON-schema-ish values.
_TYPE_VALUES_NOT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "object",
        "array",
        "string",
        "number",
        "boolean",
        "integer",
        "null",
        "text",
        "function",
        "image",
        "audio",
        "video",
        "message",
    }
)


def _resolve_tool_name_from_payload(obj: dict[str, Any]) -> str | None:
    for key in ("name", "action", "tool"):
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    t = obj.get("type")
    if isinstance(t, str) and t.strip():
        s = t.strip()
        if s.lower() in _TYPE_VALUES_NOT_TOOL_NAMES:
            return None
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", s):
            return s
    return None


def _coerce_single_tool_payload(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Build one LangChain-style tool_call dict from a loose JSON object, or return None."""
    if not isinstance(obj, dict):
        return None
    fn = obj.get("function")
    if isinstance(fn, dict):
        nm = fn.get("name")
        if isinstance(nm, str) and nm.strip():
            args = _parse_tool_arguments_field(fn.get("arguments"))
            tid = str(obj.get("id") or f"coerced-{uuid.uuid4().hex[:12]}")
            return {"name": nm.strip(), "args": args, "id": tid, "type": "tool_call"}
    name = _resolve_tool_name_from_payload(obj)
    if not name:
        return None
    args: dict[str, Any] = {}
    args.update(_parse_tool_arguments_field(obj.get("arguments")))
    if isinstance(obj.get("args"), dict):
        for k, v in obj["args"].items():
            if v is not None:
                args[k] = v
    for k, v in obj.items():
        if k in _TOOL_PAYLOAD_META or v is None:
            continue
        if isinstance(v, (dict, list)) and k != "content":
            continue
        args[k] = v
    tid = str(obj.get("id") or f"coerced-{uuid.uuid4().hex[:12]}")
    return {"name": name, "args": args, "id": tid, "type": "tool_call"}


def _collect_coerced_tool_calls_from_dict(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract 0..N tool_calls from a parsed JSON object (strict or loose shapes)."""
    built: list[dict[str, Any]] = []
    raw_calls = data.get("tool_calls")
    if isinstance(raw_calls, list):
        for tc in raw_calls:
            if isinstance(tc, dict):
                one = _coerce_single_tool_payload(tc)
                if one:
                    built.append(one)
        if built:
            return built
    one = _coerce_single_tool_payload(data)
    return [one] if one else []


def _coerce_json_in_content_to_tool_calls(msg: AIMessage) -> AIMessage:
    """Turn JSON in ``content`` (strict or loose) into real LangChain ``tool_calls``."""
    if not _env_enabled("DEEPAGENTS_COERCE_JSON_TOOL_CALLS", "1"):
        return msg
    if getattr(msg, "tool_calls", None):
        return msg
    raw_content = getattr(msg, "content", "")
    if isinstance(raw_content, list):
        return msg
    if not isinstance(raw_content, str) or not raw_content.strip():
        return msg

    data = _extract_json_object_from_text(raw_content)
    if not data:
        return msg
    built = _collect_coerced_tool_calls_from_dict(data)
    if not built:
        return msg

    logging.getLogger(__name__).info(
        "Coerced %d tool call(s) from JSON text in AIMessage.content "
        "(model did not use native tool_calls; loose keys like action/arguments supported).",
        len(built),
    )
    if hasattr(msg, "model_copy"):
        return msg.model_copy(update={"content": "", "tool_calls": built})
    return msg.copy(update={"content": "", "tool_calls": built})


def _normalize_agent_ai_message(msg: AIMessage) -> AIMessage:
    """Repair common OpenRouter / OSS model output quirks before the agent graph runs tools."""
    msg = _coerce_json_in_content_to_tool_calls(msg)
    msg = _sanitize_ai_tool_names(msg)
    return msg


class _OpenRouterToolNameSanitizer(BaseChatModel):
    """Normalize model output: JSON-in-text tool calls + ``<|channel|>…`` tool name suffixes."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    inner: Any

    @property
    def _llm_type(self) -> str:
        return "openrouter_tool_name_sanitizer"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"wrapped": getattr(self.inner, "_llm_type", type(self.inner).__name__)}

    def bind_tools(self, tools: Sequence, **kwargs: Any) -> BaseChatModel:
        if not hasattr(self.inner, "bind_tools"):
            return self
        return _OpenRouterToolNameSanitizer(inner=self.inner.bind_tools(tools, **kwargs))

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        gen = getattr(self.inner, "_generate", None)
        if gen is None:
            out = self.inner.invoke(messages, **kwargs)
            if isinstance(out, AIMessage):
                out = _normalize_agent_ai_message(out)
            return ChatResult(generations=[ChatGeneration(message=out)])
        result = gen(messages, stop=stop, run_manager=run_manager, **kwargs)
        generations: list[ChatGeneration] = []
        for g in result.generations:
            m = g.message
            if isinstance(m, AIMessage):
                m = _normalize_agent_ai_message(m)
            generations.append(ChatGeneration(message=m, generation_info=g.generation_info))
        return ChatResult(generations=generations, llm_output=result.llm_output)

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        agen = getattr(self.inner, "_agenerate", None)
        if agen is None:
            out = await self.inner.ainvoke(messages, **kwargs)
            if isinstance(out, AIMessage):
                out = _normalize_agent_ai_message(out)
            return ChatResult(generations=[ChatGeneration(message=out)])
        result = await agen(messages, stop=stop, run_manager=run_manager, **kwargs)
        generations: list[ChatGeneration] = []
        for g in result.generations:
            m = g.message
            if isinstance(m, AIMessage):
                m = _normalize_agent_ai_message(m)
            generations.append(ChatGeneration(message=m, generation_info=g.generation_info))
        return ChatResult(generations=generations, llm_output=result.llm_output)


# Demo task: small, bounded (write file → run → prove). Replace via DEEPAGENTS_USER_PROMPT_FILE.
_CALC_DEMO_USER_PROMPT = """You control a **sandbox** (shell + files). Work **step by step** with your tools.

**Goal:** a tiny **calculator CLI** and **proof** it runs in the sandbox.

**Hard requirements (do not skip):**
1. **Write** `/tmp/calc.py` that reads **one line** from stdin like `7 * 6` or `100 / 4` (three tokens: integer, one of `+ - * /`, integer; spaces as shown). Print **only** the integer/float result, or a single line `Error: ...`.
   - **Do not use `eval`, `exec`, or `compile` on the input.** Parse with `split()` and apply the operator explicitly.
2. **After** the file exists, you **must** call your shell tool (`execute`) **at least twice** with exactly:
   - `echo "7 * 6" | python3 /tmp/calc.py`
   - `echo "100 / 4" | python3 /tmp/calc.py`
   and rely on the tool output (stdout) as proof.
3. Only then give a short final summary that quotes those **exact** stdout lines.

If you only call `write_file` and stop, the task is incomplete.
Do **not** narrate a todo list as plain text — use your tools (write_file, execute, …), not prose that looks like tool names."""


def _load_user_prompt() -> str:
    path = os.environ.get("DEEPAGENTS_USER_PROMPT_FILE", "").strip()
    if not path:
        return _CALC_DEMO_USER_PROMPT
    with open(path, encoding="utf-8") as f:
        return f.read().strip() or _CALC_DEMO_USER_PROMPT


def _invoke_recursion_limit() -> int:
    raw = os.environ.get("DEEPAGENTS_RECURSION_LIMIT", "40").strip()
    try:
        n = int(raw)
    except ValueError:
        return 40
    return max(5, min(n, 500))


def _print_messages_evidence(result: object) -> None:
    """Readable tail of the graph state: tool stdout/stderr and final model text."""
    if not isinstance(result, dict):
        _log(str(result)[:4000])
        return
    msgs = result.get("messages") or []
    _log("\n========== Evidence: tool runs + model steps ==========")
    for i, m in enumerate(msgs):
        label = f"[{i}] {type(m).__name__}"
        if isinstance(m, ToolMessage):
            name = getattr(m, "name", "tool") or "tool"
            body = str(getattr(m, "content", ""))
            _log(f"\n--- Tool {label} [{name}] ---\n{body if len(body) <= 6000 else body[:6000] + '\n… [truncated]'}")
        elif isinstance(m, AIMessage):
            tool_calls = getattr(m, "tool_calls", None) or []
            raw_content = getattr(m, "content", "")
            text = raw_content if isinstance(raw_content, str) else str(raw_content)
            text = text.strip()
            if tool_calls:
                _log(f"\n--- Model {label} → tool_calls ---")
                for tc in tool_calls:
                    _log(f"  {tc.get('name')!r} {tc.get('args')!r}")
            if text:
                _log(f"\n--- Model {label} text ---\n{text if len(text) <= 4000 else text[:4000] + '…'}")
            if not tool_calls and not text:
                _log(f"\n--- Model {label} (empty content, no tool_calls) ---")
        else:
            preview = str(getattr(m, "content", m))[:500]
            _log(f"\n--- Other {label} ---\n{preview}")

    saw_execute = any(
        isinstance(m, ToolMessage) and (getattr(m, "name", "") or "") == "execute" for m in msgs
    )
    hallucinated_tools = False
    for m in msgs:
        if not isinstance(m, AIMessage):
            continue
        tcs = getattr(m, "tool_calls", None) or []
        raw = getattr(m, "content", "")
        text = raw if isinstance(raw, str) else str(raw)
        if not tcs and "write_todos" in text:
            hallucinated_tools = True
            break

    if not saw_execute:
        _log(
            "\n*** Incomplete run: no ToolMessage named `execute`. Common causes: (1) weak model "
            "(e.g. ``openrouter/free`` or a small local Ollama model) skipped tools; (2) model wrote "
            "a *text* plan (e.g. the word write_todos) instead of issuing real tool_calls — try a "
            "stronger OPENROUTER_MODEL / OLLAMA_MODEL; (3) task too vague so the graph never reached "
            "shell proof. ***\n"
        )
    if hallucinated_tools:
        _log(
            "*** Note: at least one AIMessage looks like a fake todo list (tool names as prose). "
            "The model must emit structured tool_calls, not plain text. ***\n"
        )
    _log("\n========== End evidence ==========\n")


def _normalize_openrouter_model(model: str) -> str:
    slug = model.strip()
    if not slug:
        return _DEFAULT_OPENROUTER_MODEL
    mapped = _OPENROUTER_MODEL_ALIASES.get(slug)
    if mapped and mapped != slug:
        if mapped == "openrouter/free":
            _log(
                f"Note: {slug!r} is not served on OpenRouter anymore (404). "
                f"Using {mapped!r}. Pin a current free id from https://openrouter.ai/models?q=free "
                "via OPENROUTER_MODEL if you need a fixed model."
            )
        else:
            _log(f"Note: normalized OPENROUTER_MODEL {slug!r} -> {mapped!r}")
        return mapped
    return slug


def _build_openrouter_chat() -> ChatOpenAI:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        print(
            "Set OPENROUTER_API_KEY (free key: https://openrouter.ai/keys ).\n"
            "Pick a :free model from https://openrouter.ai/models and set OPENROUTER_MODEL if the default fails.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    model = _normalize_openrouter_model(
        os.environ.get("OPENROUTER_MODEL", _DEFAULT_OPENROUTER_MODEL)
    )
    _log(f"OpenRouter chat model: {model!r}")
    referer = os.environ.get("OPENROUTER_HTTP_REFERER", "http://localhost").strip()
    title = os.environ.get("OPENROUTER_X_TITLE", "deepagents-my-sandbox-example").strip()

    return ChatOpenAI(
        model=model,
        api_key=key,
        openai_api_base="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": referer,
            "X-Title": title,
        },
        temperature=0.1,
        timeout=120.0,
        max_retries=2,
    )


def _use_ollama() -> bool:
    """Use local Ollama (OpenAI-compatible ``/v1`` on port 11434 by default)."""
    v = os.environ.get("USE_OLLAMA", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    return os.environ.get("LLM_BACKEND", "").strip().lower() == "ollama"


def _build_ollama_chat() -> ChatOpenAI:
    """Ollama exposes an OpenAI-compatible API at ``<base>/v1`` (see Ollama docs)."""
    base = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2").strip()
    if not model:
        print("OLLAMA_MODEL is empty.", file=sys.stderr)
        raise SystemExit(2)
    _log(f"Ollama chat: base={base!r} model={model!r} (pull in Ollama app if requests fail)")
    # Ollama accepts a placeholder API key for OpenAI-compatible clients.
    api_key = os.environ.get("OLLAMA_API_KEY", "ollama").strip() or "ollama"
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        openai_api_base=f"{base}/v1",
        temperature=float(os.environ.get("OLLAMA_TEMPERATURE", "0.1")),
        timeout=float(os.environ.get("OLLAMA_TIMEOUT", "120")),
        max_retries=int(os.environ.get("OLLAMA_MAX_RETRIES", "2")),
    )


def _build_llm() -> ChatOpenAI:
    if _use_ollama():
        return _build_ollama_chat()
    return _build_openrouter_chat()


def _maybe_disable_parallel_tool_calls(llm: Any) -> Any:
    """Avoid write_file + execute racing when both appear in one assistant turn.

    OpenAI-compatible APIs default to parallel tool calls; the sandbox then may run
    ``python3 ...`` before the file write finishes → ``No such file or directory``.
    Opt back in with ``DEEPAGENTS_ALLOW_PARALLEL_TOOL_CALLS=1``.
    """
    if _env_enabled("DEEPAGENTS_ALLOW_PARALLEL_TOOL_CALLS", "0"):
        return llm
    if hasattr(llm, "bind"):
        return llm.bind(parallel_tool_calls=False)
    return llm


def build_deep_agent_session(
    *,
    api_url: str | None = None,
    api_key: str | None = None,
    request_timeout: float = 600.0,
) -> tuple[Any, Any, int]:
    """Build chat LLM + deep agent + sandbox. Caller must ``sandbox.kill()`` when done.

    LLM from OpenRouter (``OPENROUTER_API_KEY``) unless ``USE_OLLAMA=1`` / ``LLM_BACKEND=ollama``.

    Used by ``examples/deepagent_ui/server.py`` and by :func:`main` below.
    """
    api_url = (api_url or os.environ.get("MY_SANDBOX_API_URL", "http://127.0.0.1:8000")).rstrip("/")
    api_key = api_key or os.environ.get("MY_SANDBOX_API_KEY") or None

    llm: Any = _build_llm()
    if _env_enabled("DEEPAGENTS_ALLOW_PARALLEL_TOOL_CALLS", "0"):
        pass
    else:
        llm = _maybe_disable_parallel_tool_calls(llm)
    if _env_enabled("DEEPAGENTS_COERCE_JSON_TOOL_CALLS", "1") or _env_enabled(
        "DEEPAGENTS_SANITIZE_TOOL_NAMES", "1"
    ):
        llm = _OpenRouterToolNameSanitizer(inner=llm)

    rlim = _invoke_recursion_limit()
    sb = Sandbox.create(api_url=api_url, api_key=api_key, request_timeout=request_timeout)
    backend_kwargs: dict[str, Any] = {}
    _race = os.environ.get("MY_SANDBOX_EXECUTE_RACE_WAIT_SEC", "").strip()
    if _race.lower() in ("0", "false", "no", "off"):
        backend_kwargs["execute_file_race_wait_sec"] = 0.0
    elif _race:
        backend_kwargs["execute_file_race_wait_sec"] = float(_race)
    backend = SandboxDeepAgentBackend(sandbox=sb, **backend_kwargs)
    agent = create_deep_agent(
        model=llm,
        system_prompt=(
            "You are a coding agent with shell and file access inside a sandbox. "
            "Always use real tool_calls (structured tools), not plain-text pretend tool invocations. "
            "After writing files, run `execute` to prove behavior. Keep tasks incremental; avoid huge "
            "unbounded projects in one shot.\n"
            "Never put tools inside XML, markdown fences, or lines like `<tool_call>` — the runtime "
            "only accepts native JSON tool_calls from the API.\n"
            "For write_file and read_file use the argument name **file_path** (absolute path), not `path`. "
            "Never claim command output unless a real `execute` tool ran; do not invent stdout.\n"
            "Do not issue `write_file` and `execute` on the same file in a single turn unless the "
            "executor runs tools strictly in order; prefer write_file, see success, then execute."
        ),
        backend=backend,
    )
    return agent, sb, rlim


def main() -> int:
    # Optional: see LangChain / HTTP retries (can be noisy).
    if os.environ.get("DEEPAGENTS_DEBUG_LOG", "").strip() in ("1", "true", "yes"):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    api_url = os.environ.get("MY_SANDBOX_API_URL", "http://127.0.0.1:8000").rstrip("/")
    api_key = os.environ.get("MY_SANDBOX_API_KEY") or None

    _log("Starting deepagents + my_sandbox example…")
    rlim = _invoke_recursion_limit()
    _log(f"Graph recursion_limit={rlim} (raise with DEEPAGENTS_RECURSION_LIMIT if the task is larger).")
    if _env_enabled("DEEPAGENTS_ALLOW_PARALLEL_TOOL_CALLS", "0"):
        _log("LLM: parallel tool calls allowed (DEEPAGENTS_ALLOW_PARALLEL_TOOL_CALLS=1).")
    else:
        _log(
            "LLM: parallel_tool_calls=False (provider hint). "
            "LangGraph may still run multiple tools from one message in parallel — "
            "SandboxDeepAgentBackend.execute waits briefly for missing .py paths (see docstring)."
        )
    if _env_enabled("DEEPAGENTS_COERCE_JSON_TOOL_CALLS", "1") or _env_enabled(
        "DEEPAGENTS_SANITIZE_TOOL_NAMES", "1"
    ):
        _log(
            "Wrapped LLM: tool-call repairs — JSON-in-text → native tool_calls; "
            "optional <|channel|> suffix strip (see DEEPAGENTS_* env vars)."
        )

    _log(
        "Calling Sandbox.create — this HTTP request can take **minutes** on first run while "
        "the API pulls the Docker image (e.g. python:3.11). You are not hung; wait for the next line."
    )
    agent, sb, rlim = build_deep_agent_session(
        api_url=api_url, api_key=api_key, request_timeout=600.0
    )
    _log(f"Sandbox ready: {sb!r}")

    user_prompt = _load_user_prompt()
    if os.environ.get("DEEPAGENTS_USER_PROMPT_FILE", "").strip():
        _log(f"User prompt loaded from DEEPAGENTS_USER_PROMPT_FILE (length={len(user_prompt)} chars).")

    _log("Creating deep agent with SandboxDeepAgentBackend…")

    _log("Agent built. Invoking (LLM + tools; each step can be slow on free models)…")

    try:
        invoke_cfg: dict[str, Any] = {"recursion_limit": rlim}
        try:
            out = agent.invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": user_prompt,
                        }
                    ]
                },
                invoke_cfg,
            )
        except GraphRecursionError as e:
            _log(
                f"Stopped: hit recursion_limit={rlim} ({e!s}). "
                "Increase DEEPAGENTS_RECURSION_LIMIT or narrow the user prompt."
            )
            out = {"messages": []}
        _log("Done.")
        _print_messages_evidence(out)
        if os.environ.get("DEEPAGENTS_DUMP_STATE", "").strip() in ("1", "true", "yes"):
            _log("DEEPAGENTS_DUMP_STATE=1 → raw state repr (truncated):")
            _log(str(out)[:8000])
        return 0
    finally:
        _log("Killing sandbox…")
        sb.kill()
        _log("Exiting.")


if __name__ == "__main__":
    raise SystemExit(main())
