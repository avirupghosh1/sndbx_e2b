#!/usr/bin/env python3
"""
Demonstrate an *agent* whose Python runs *inside* the sandbox container.

Flow (high level)
-----------------
1. Your machine runs this script and calls the sandbox API (via ``my_sdk``).
2. ``POST /sandboxes/{id}/agents/spawn`` uploads ``agent_code`` into the container and the API
   starts a worker thread that runs ``python3 /tmp/agent_<id>.py`` there.
3. With ``config["single_run"]: True``, that command runs once (good for a self-contained loop
   that builds files then deletes them). Without it, the API re-runs the script every
   ``exec_interval_sec`` until you kill the agent.

Optional LLM hook
-----------------
If ``CHAT_COMPLETION_URL`` is set, this script POSTs an OpenAI-style chat completion request
and uses ``choices[0].message.content`` as the agent body (strip Markdown code fences if present).
Point it at your router; the sandbox API does not call the LLM for you.

Env
---
MY_SANDBOX_API_URL   default http://127.0.0.1:8000
MY_SANDBOX_API_KEY   optional (X-API-Key)
CHAT_COMPLETION_URL  optional
CHAT_COMPLETION_KEY  optional Authorization: Bearer ...
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Repo layout: examples/ next to my_sandbox_sdk/
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SDK_SRC = os.path.join(_REPO_ROOT, "my_sandbox_sdk")
if _SDK_SRC not in sys.path:
    sys.path.insert(0, _SDK_SRC)

from my_sdk.sync.sandbox import Sandbox  # noqa: E402


DEFAULT_AGENT_CODE = r"""
import os
import shutil
import time

ROOT = "/tmp/agent_demo_build"
for i in range(3):
    os.makedirs(ROOT, exist_ok=True)
    path = os.path.join(ROOT, "artifact_%s.txt" % (i,))
    with open(path, "w") as f:
        f.write("build step %s\n" % (i,))
    print("wrote", path)
    time.sleep(0.15)
if os.path.isdir(ROOT):
    shutil.rmtree(ROOT)
    print("deleted", ROOT)
print("agent demo finished")
""".strip()


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    return t


def fetch_agent_code_from_llm(url: str) -> Optional[str]:
    """POST OpenAI-compatible chat completions; return Python source or None."""
    key = os.environ.get("CHAT_COMPLETION_KEY", "").strip()
    payload: Dict[str, Any] = {
        "model": os.environ.get("CHAT_COMPLETION_MODEL", "gpt-4o-mini"),
        "messages": [
            {
                "role": "user",
                "content": (
                    "Return only Python 3 source code, no markdown. "
                    "Script: create /tmp/agent_demo_build, write 3 small text files in a loop, "
                    "print each path, then delete the directory tree with shutil.rmtree."
                ),
            }
        ],
        "temperature": 0.2,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as e:
        print("LLM request failed:", e)
        return None
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        print("Unexpected LLM response shape:", body)
        return None
    return _strip_code_fence(str(content))


def main() -> int:
    api_url = os.environ.get("MY_SANDBOX_API_URL", "http://127.0.0.1:8000").rstrip("/")
    api_key="test-key-12345"
    llm_url = os.environ.get("CHAT_COMPLETION_URL", "").strip()

    agent_code = DEFAULT_AGENT_CODE

    if llm_url:
        generated = fetch_agent_code_from_llm(llm_url)
        if generated:
            agent_code = generated
            print("Using agent code from CHAT_COMPLETION_URL")
        else:
            print("Falling back to DEFAULT_AGENT_CODE")

    print("Creating sandbox …")
    sb = Sandbox.create(api_url=api_url, api_key=api_key, request_timeout=600.0)
    try:
        print("Spawning agent (single_run) …")
        spawn = sb.spawn_agent(
            agent_name="build_loop_demo",
            agent_code=agent_code,
            config={"single_run": True, "timeout": 300},
        )
        agent_id = spawn.get("agent_id")
        if not agent_id:
            print("Spawn failed:", spawn)
            return 1
        print("agent_id:", agent_id)

        deadline = time.time() + 120
        state = ""
        while time.time() < deadline:
            info = sb.get_agent(agent_id)
            state = str(info.get("state", ""))
            print("  agent state:", state)
            if state in ("stopped", "failed"):
                break
            time.sleep(0.5)

        print("Listing /tmp on sandbox …")
        r = sb.commands.run("ls -la /tmp | head -40 || true")
        print("exit:", r.exit_code)
        print(r.stdout or r.stderr or "(no output)")

        print("Killing agent record (cleanup API thread) …")
        sb.kill_agent(agent_id)
        return 0 if state == "stopped" else 2
    finally:
        print("Killing sandbox …")
        sb.kill()


if __name__ == "__main__":
    raise SystemExit(main())
