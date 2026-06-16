# Sandbox API + SDK — how to run, connect, and use WebSockets

One place for **basic operation**: start the API, use the **Python SDK** over HTTP, and open the **agent WebSocket** (E2B-style) to talk to a process inside the guest (for example `agentlib-e2b-server` on port **8765**).

---

## 1. Prerequisites

- **Docker** running (`docker info` works).
- **Python 3.12+** recommended (API + SDK; see `api_server/requirements.txt`).

---

## 2. Configuration (two small files)

| Copy this | To this | Purpose |
|-----------|---------|---------|
| `api_server/.env.example` | `api_server/.env` | Server: set at least **`API_KEY`** and **`E2B_DROPIN_WS_SECRET`** (random hex, ~24+ bytes) so WebSocket drop-in works. |
| `.env.example` (repo root) | `.env` (repo root) | Client: **`MY_SDK_API_URL`**, **`MY_SDK_API_KEY`** (or **`SANDBOX_API_URL`** / **`API_KEY`**). |

Generate a WS secret:

```bash
python3 -c "import secrets; print(secrets.token_hex(24))"
```

---

## 3. Start the API

```bash
cd api_server
cp .env.example .env
# edit .env — set E2B_DROPIN_WS_SECRET and API_KEY
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Default REST base: **`http://127.0.0.1:8000`**. Use the same host in the SDK.

---

## 4. Install the SDK

From the **repository root** (parent of `api_server/`):

```bash
pip install -e "./my_sandbox_sdk[ws]"
```

The **`[ws]`** extra is required for **`open_agent_websocket`**.

---

## 5. Basic SDK usage (HTTP)

Point at your API (env vars **`MY_SDK_API_URL`** / **`MY_SDK_API_KEY`**, or pass `api_url=` / `api_key=` explicitly).

**Sync**

```python
from my_sdk import Sandbox

sandbox = Sandbox.create(
    api_url="http://127.0.0.1:8000",
    api_key="test-key-12345",
    template_id="python:3.11",
)
print(sandbox.sandbox_id)
out = sandbox.commands.run("uname -a")
print(out.stdout, out.exit_code)
sandbox.kill()
```

**Async**

```python
import asyncio
from my_sdk import AsyncSandbox

async def main():
    s = await AsyncSandbox.create(
        api_url="http://127.0.0.1:8000",
        api_key="test-key-12345",
        template_id="python:3.11",
    )
    out = await s.commands.run("uname -a")
    print(out.stdout)
    await s.kill()

asyncio.run(main())
```

---

## 6. How the agent WebSocket fits in

1. You have a **running** sandbox (`Sandbox.create` / `AsyncSandbox.create`).
2. The control plane exposes **`GET /sandboxes/{id}/e2b-connection`**: it returns **`ws_url`**, **`traffic_access_token`**, and related fields.
3. Your client opens a **WebSocket** to **`ws_url`**, with header **`e2b-traffic-access-token: <traffic_access_token>`** (or query `?traffic_token=` if you use that mode).
4. The API **proxies** frames to whatever listens in the guest on **`E2B_DROPIN_AGENT_PORT`** (default **8765**), usually **`agentlib-e2b-server`**.

The SDK calls **`GET …/e2b-connection`** after **`create`** (and after **`connect`** when **`with_e2b=True`**, the default) so `ws_url` and `traffic_access_token` are ready for **`open_agent_websocket`**.

---

## 7. Connect with the SDK (recommended)

**Async** — context manager sends the traffic header for you:

```python
import asyncio
import json
from my_sdk import AsyncSandbox

async def main():
    s = await AsyncSandbox.create(
        api_url="http://127.0.0.1:8000",
        api_key="test-key-12345",
        template_id="", #USE A DOCKERFILE/IMAGE  TO LISTEN TO A PORT FROM GUEST SIDE THEN FROM CLIENT SIDE THROUGH ACCESS TOKEN AND WS_URL WE CAN REACH TO THAT PORT AND COMMUNICATION IS ENABLED
    )
    async with s.open_agent_websocket(open_timeout=60) as ws:
        await ws.send(json.dumps({
            "type": "prompt",
            "data": {
                "auth_token": "dev-session",
                "text": "Hello from client",
                "credentials": {"openai": {"OPENAI_API_KEY": "sk-..."}},
            },
        }))
        msg = await ws.recv()
        print(msg)
    await s.kill()

asyncio.run(main())
```

**Sync**

```python
import json
from my_sdk import Sandbox

with Sandbox.create(
    api_url="http://127.0.0.1:8000",
    api_key="test-key-12345",
    template_id="",
) as s:
    with s.open_agent_websocket(open_timeout=60) as ws:
        ws.send(json.dumps({"type": "prompt", "data": {"auth_token": "x", "text": "hi"}}))
        print(ws.recv())
```

Adjust the **`prompt`** JSON to match your guest (OpenAI credentials block above matches the current **agentlib** guest path).

---

## 8. Connect without the SDK (any WebSocket client)

1. `GET http://127.0.0.1:8000/sandboxes/{id}/e2b-connection` with header **`X-API-Key: <API_KEY>`**.
2. Read **`ws_url`** and **`traffic_access_token`** from the JSON body.
3. Open **`ws_url`** with header **`e2b-traffic-access-token: <traffic_access_token>`**.

Repo helper script: **`ws_chat_probe.py`** (expects **`WS_URL`**, **`TRAFFIC_TOKEN`**, **`OPENAI_API_KEY`** env vars).

---

## 9. Where everything lives

| Path | Role |
|------|------|
| `api_server/` | FastAPI app (`main.py`), Docker orchestration, WS proxy, envd routes. |
| `my_sandbox_sdk/` | `Sandbox` / `AsyncSandbox`, commands, files, `open_agent_websocket`. |
| `api_server/docs/E2B_DROPIN_TESTING.md` | Longer WS / token troubleshooting. |

**Other READMEs** in this repo (`api_server/README.md`, `my_sandbox_sdk/README.md`) only point here for quickstart; they are not required reading for basic operation.

---

## What to commit (this repo)

`.gitignore` is set so **only** the top-level items below are meant for git by default:

- **`README.md`** — this guide  
- **`api_server/`** — full API (handlers, `envd_guest/`, `e2b_dropin/`, `orchestrator/`, `docs/`, `requirements.txt`, `.env.example`, …)  
- **`my_sandbox_sdk/`** — installable SDK  
- **`.env.example`** — client env template (no secrets)  

Everything else under `intern_1strepo/` (examples, `check_Code.py`, `e2b_shim/`, `docs/`, …) stays **untracked** unless you add a `!/path` line in `.gitignore`.

**Enough to “get the work done”:** those four are sufficient to run the API, install the SDK from this tree, and follow the WebSocket flow in this README. Add **`ws_chat_probe.py`** only if you want the one-file WS probe in the same repo (uncomment the line in `.gitignore`). For Custodian-style host code, add **`check_Code.py`** + vendored **agentlib** elsewhere (see `api_server/docs/AGENTLIB_AND_CHECK_CODE.md`) — not required for API + SDK alone.

