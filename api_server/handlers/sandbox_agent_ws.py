"""E2B-style agent WebSocket proxy + connection metadata (Docker/gVisor only).

``GET /sandboxes/{id}/e2b-connection`` mints ``traffic_access_token``.
``WS /sandboxes/{id}/agent-ws`` validates token (or ``X-API-Key``) and bidirectionally proxies
to the in-container agent WebSocket (by default ``ws://127.0.0.1:<published>/`` when Docker
publishes ``E2B_DROPIN_AGENT_PORT``, else ``ws://<container_ip>:<port>/``).
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket

from async_runner import run_io
from config import get_config
from e2b_dropin.tokens import verify_traffic_token
from e2b_dropin.ws_bridge import connect_upstream_with_retries, run_starlette_upstream_pumps
from middleware import validate_api_key, SandboxNotFoundException
from middleware.auth import VALID_API_KEYS
from models import SandboxE2bConnectionResponse
from orchestrator import SandboxManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandboxes", tags=["e2b-drop-in"])


def _public_ws_base(request: Request) -> str:
    cfg = get_config()
    if (cfg.E2B_DROPIN_PUBLIC_WS_BASE or "").strip():
        return cfg.E2B_DROPIN_PUBLIC_WS_BASE.strip().rstrip("/")
    u = str(request.base_url).rstrip("/")
    if u.startswith("https://"):
        return "wss://" + u[len("https://") :]
    if u.startswith("http://"):
        return "ws://" + u[len("http://") :]
    return u


def _e2b_style_host(ws_url: str) -> str:
    p = urlparse(ws_url)
    path = (p.path or "").rstrip("/")
    return p.netloc + path


@router.get("/{sandbox_id}/e2b-connection", response_model=SandboxE2bConnectionResponse)
async def get_e2b_connection(
    sandbox_id: str,
    request: Request,
    api_key: str = Depends(validate_api_key),
    sandbox_manager: SandboxManager = Depends(lambda: SandboxManager.__dict__.get("instance")),
):
    """Mint ``traffic_access_token`` and return WebSocket URL for E2B-style clients."""
    cfg = get_config()
    if not (cfg.E2B_DROPIN_WS_SECRET or "").strip():
        raise HTTPException(
            status_code=503,
            detail="E2B drop-in is not configured: set E2B_DROPIN_WS_SECRET in the API environment.",
        )
    sid = sandbox_id.strip()
    row = await run_io(sandbox_manager.get_sandbox, sid)
    if not row:
        raise SandboxNotFoundException(sid)
    if not await run_io(sandbox_manager.is_running, sid):
        raise HTTPException(status_code=409, detail="Sandbox is not running")
    upstream = await run_io(sandbox_manager.get_e2b_agent_upstream_ws_uri, sid)
    if not upstream:
        raise HTTPException(
            status_code=501,
            detail="E2B drop-in WebSocket upstream is only available for Docker/gVisor sandboxes.",
        )
    base = _public_ws_base(request)
    ws_url = f"{base}/sandboxes/{sid}/agent-ws"
    token = await run_io(sandbox_manager.mint_e2b_traffic_token, sid)
    port = int(getattr(cfg, "E2B_DROPIN_AGENT_PORT", 8765))
    return SandboxE2bConnectionResponse(
        sandbox_id=sid,
        agent_port=port,
        ws_url=ws_url,
        traffic_access_token=token,
        e2b_style_host=_e2b_style_host(ws_url),
    )


@router.websocket("/{sandbox_id}/agent-ws")
async def agent_websocket_proxy(websocket: WebSocket, sandbox_id: str):
    """Bidirectional WebSocket proxy to in-container agent server (transparent JSON)."""
    cfg = get_config()
    secret = (cfg.E2B_DROPIN_WS_SECRET or "").strip()
    sid = sandbox_id.strip()

    traffic = (websocket.headers.get("e2b-traffic-access-token") or "").strip()
    query_token = (websocket.query_params.get("traffic_token") or "").strip()
    if not traffic and query_token:
        traffic = query_token

    api_key = (websocket.headers.get("X-API-Key") or "").strip()
    valid_api = bool(api_key and api_key in VALID_API_KEYS)

    authorized = False
    if valid_api:
        authorized = True
    elif secret and traffic:
        payload = verify_traffic_token(secret, traffic)
        if payload and str(payload.get("sid") or "") == sid:
            authorized = True

    if not authorized:
        await websocket.close(code=4401)
        return

    sm = SandboxManager.instance
    if sm is None:
        await websocket.close(code=1011)
        return

    if not sm.is_running(sid):
        await websocket.close(code=4404)
        return

    upstream_uri = sm.get_e2b_agent_upstream_ws_uri(sid)
    if not upstream_uri:
        await websocket.close(code=1011)
        return

    await websocket.accept()

    upstream_cm = None
    pump_exc: BaseException | None = None
    entered_upstream = False
    open_to = float(getattr(cfg, "E2B_DROPIN_UPSTREAM_OPEN_TIMEOUT_SEC", 60.0))
    connect_retries = int(getattr(cfg, "E2B_DROPIN_UPSTREAM_CONNECT_RETRIES", 3))
    retry_delay = float(getattr(cfg, "E2B_DROPIN_UPSTREAM_RETRY_DELAY_SEC", 1.0))
    agent_port = int(getattr(cfg, "E2B_DROPIN_AGENT_PORT", 8765))

    try:
        upstream_cm, upstream = await connect_upstream_with_retries(
            upstream_uri,
            open_timeout=open_to,
            connect_retries=connect_retries,
            retry_delay=retry_delay,
        )
        entered_upstream = True
        try:
            await run_starlette_upstream_pumps(websocket, upstream)
        except BaseException as e:
            pump_exc = e
            raise
        finally:
            if upstream_cm is not None:
                await upstream_cm.__aexit__(
                    type(pump_exc) if pump_exc else None,
                    pump_exc,
                    pump_exc.__traceback__ if pump_exc else None,
                )
                upstream_cm = None
    except Exception as ex:  # noqa: BLE001
        if not entered_upstream:
            logger.warning(
                "agent_ws upstream connect failed sandbox_id=%s uri=%s: %s. "
                "Ensure a WebSocket server listens on 0.0.0.0:%s in the guest. "
                "If the API runs inside Docker and cannot route to the sandbox bridge IP, "
                "see api_server/docs/E2B_DROP_IN_IMPLEMENTATION.md (item B7). "
                "Tune E2B_DROPIN_UPSTREAM_OPEN_TIMEOUT_SEC (default 60) and "
                "E2B_DROPIN_UPSTREAM_CONNECT_RETRIES if the guest is slow to start.",
                sid,
                upstream_uri,
                ex,
                agent_port,
            )
        else:
            logger.warning("agent_ws error sandbox_id=%s: %s", sid, ex, exc_info=True)
    finally:
        try:
            await asyncio.sleep(0)
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
