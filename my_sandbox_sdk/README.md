# My Sandbox SDK

**Quickstart (create sandbox, commands, WebSocket):** use the repository **[README.md](../README.md)** at the repo root — that is the single guide for basic operation.

## Install

```bash
pip install -e ".[ws]"
```

`[ws]` is required for `Sandbox.open_agent_websocket` / `AsyncSandbox.open_agent_websocket`.

## Env vars

See **`.env.example`** in the repo root (`MY_SDK_API_URL`, `MY_SDK_API_KEY`, or `SANDBOX_API_URL` / `E2B_API_URL` + keys).

## Package layout

Python import path: **`my_sdk`** (see `pyproject.toml` / `src` layout in this directory).

For deeper API surface (every method, metrics, templates), read the source under `my_sdk/` or open an issue; the root README stays intentionally short.
