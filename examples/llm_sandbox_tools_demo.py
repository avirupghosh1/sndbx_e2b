#!/usr/bin/env python3
"""
Option 2: **LLM outside** the sandbox; the sandbox is only a **tool** (files + shell) via this API.

This script is **vendor-neutral**: set ``CHAT_COMPLETION_URL`` to any **OpenAI-compatible**
``/v1/chat/completions`` endpoint (LM Studio, vLLM, OpenAI, **Ollama** at
``http://127.0.0.1:11434/v1/chat/completions``, your own router, etc.).

Required environment
----------------------
CHAT_COMPLETION_URL    e.g. https://api.openai.com/v1/chat/completions
CHAT_COMPLETION_MODEL  model id accepted by that server
MY_SANDBOX_API_URL     default http://127.0.0.1:8000
MY_SANDBOX_API_KEY     optional (X-API-Key)

Optional
--------
CHAT_COMPLETION_KEY    Bearer token if the completions server requires it
MAX_LLM_TURNS          default 18
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SDK_SRC = os.path.join(_REPO_ROOT, "my_sandbox_sdk")
if _SDK_SRC not in sys.path:
    sys.path.insert(0, _SDK_SRC)

from my_sdk.sync.sandbox import Sandbox  # noqa: E402

WORKSPACE = "/workspace"


def strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def extract_json_object(text: str) -> Optional[str]:
    t = strip_code_fence(text)
    try:
        json.loads(t)
        return t
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", t)
    if m:
        return m.group(0)
    return None


def safe_workspace_path(path: str) -> bool:
    if not path or not isinstance(path, str):
        return False
    p = path.strip()
    if not p.startswith(WORKSPACE + "/") and p != WORKSPACE:
        return False
    if ".." in p:
        return False
    return True


def chat_completion(
    url: str,
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
) -> str:
    key = os.environ.get("CHAT_COMPLETION_KEY", "").strip()
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.15,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = Request(url, data=data, headers=headers, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return str(body["choices"][0]["message"]["content"])


def execute_tool(sb: Sandbox, step: Dict[str, Any]) -> str:
    """Run one JSON tool step; return text for the LLM or ``DONE``."""
    action = (step.get("action") or "").strip().lower()
    if action == "done":
        return "DONE"

    if action == "write_file":
        path = step.get("path", "")
        content = step.get("content", "")
        if not safe_workspace_path(str(path)):
            return "ERROR: path must stay under /workspace (no ..)."
        sb.files.write(str(path), str(content) if content is not None else "")
        return "OK: wrote %r (%s bytes)." % (path, len(str(content)))

    if action == "read_file":
        path = step.get("path", "")
        if not safe_workspace_path(str(path)):
            return "ERROR: invalid path."
        try:
            text = sb.files.read(str(path))
        except Exception as e:
            return "ERROR reading file: %s" % (e,)
        if len(text) > 12000:
            text = text[:12000] + "\n... (truncated)"
        return "FILE %r:\n%s" % (path, text)

    if action == "list_dir":
        path = step.get("path", WORKSPACE)
        if not safe_workspace_path(str(path)):
            return "ERROR: list only under /workspace."
        try:
            entries = sb.files.list(str(path))
        except Exception as e:
            return "ERROR listing: %s" % (e,)
        names = ["%s (%s)" % (e.name, e.type) for e in entries[:200]]
        return "LIST %r:\n%s" % (path, "\n".join(names) if names else "(empty)")

    if action == "run_command":
        cmd = step.get("command", "")
        if not isinstance(cmd, str) or not cmd.strip():
            return "ERROR: missing command string."
        low = cmd.lower()
        for bad in ("curl ", "wget ", "nc ", "/var/run/docker", "docker "):
            if bad in low:
                return "ERROR: command blocked in demo."
        r = sb.commands.run(cmd.strip(), cwd=WORKSPACE, timeout=60.0)
        out = (r.stdout or "") + (("\nstderr:\n" + r.stderr) if r.stderr else "")
        if len(out) > 8000:
            out = out[:8000] + "\n... (truncated)"
        return "EXIT %s\n%s" % (r.exit_code, out or "(no output)")

    return "ERROR: unknown action %r." % (action,)


SYSTEM_PROMPT = """You are an autonomous coding agent. All project files MUST live under /workspace.

Each turn reply with exactly ONE JSON object (no markdown, no prose):
{
  "thought": "short plan",
  "action": "write_file" | "run_command" | "read_file" | "list_dir" | "done",
  "path": "/workspace/..." ,
  "content": "file body for write_file",
  "command": "shell for run_command"
}

Build /workspace/calc.py: add, subtract, multiply, divide (divide raises ValueError on div by zero).
Include if __name__ == '__main__': self-checks printing OK. Then run_command python3 /workspace/calc.py.
When tests pass, action \"done\".
"""


def main() -> int:
    llm_url = os.environ.get("CHAT_COMPLETION_URL", "").strip()
    if not llm_url:
        print(
            "Set CHAT_COMPLETION_URL to an OpenAI-compatible chat completions URL "
            "(e.g. https://api.openai.com/v1/chat/completions).",
            file=sys.stderr,
        )
        return 2

    api_url = os.environ.get("MY_SANDBOX_API_URL", "http://127.0.0.1:8000").rstrip("/")
    api_key = os.environ.get("MY_SANDBOX_API_KEY") or None
    model = os.environ.get("CHAT_COMPLETION_MODEL", "").strip()
    if not model:
        print("Set CHAT_COMPLETION_MODEL.", file=sys.stderr)
        return 2

    max_turns = int(os.environ.get("MAX_LLM_TURNS", "18"))

    print("LLM:", llm_url)
    print("Model:", model)
    print("Creating sandbox …")
    sb = Sandbox.create(api_url=api_url, api_key=api_key, request_timeout=600.0)
    try:
        sb.commands.run("mkdir -p %s" % WORKSPACE, timeout=30.0)

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Implement the calculator in /workspace/calc.py and verify. "
                    "Reply with JSON only each turn."
                ),
            },
        ]

        for turn in range(1, max_turns + 1):
            print("\n--- LLM turn %s ---" % turn)
            try:
                raw = chat_completion(llm_url, model, messages)
            except (HTTPError, URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
                print("LLM call failed:", e)
                return 3

            blob = extract_json_object(raw)
            if not blob:
                print("Unparseable model output:\n", raw[:1500])
                messages.append(
                    {
                        "role": "user",
                        "content": "ERROR: reply with a single JSON object only.",
                    }
                )
                continue

            try:
                step = json.loads(blob)
            except json.JSONDecodeError as e:
                messages.append({"role": "user", "content": "ERROR: invalid JSON: %s" % e})
                continue

            print("thought:", step.get("thought", ""))
            print("action:", step.get("action"))

            obs = execute_tool(sb, step)
            if obs == "DONE":
                print("Model signaled done.")
                break
            print("observation (short):", obs[:400] + ("…" if len(obs) > 400 else ""))
            messages.append({"role": "assistant", "content": blob})
            messages.append(
                {"role": "user", "content": "TOOL RESULT:\n%s\n\nNext JSON only." % obs}
            )
        else:
            print("Max turns reached.")

        r = sb.commands.run("python3 /workspace/calc.py", cwd=WORKSPACE, timeout=30.0)
        print("\nFinal: exit", r.exit_code)
        print(r.stdout or r.stderr or "")
        return 0 if r.exit_code == 0 else 1
    finally:
        sb.kill()


if __name__ == "__main__":
    raise SystemExit(main())
