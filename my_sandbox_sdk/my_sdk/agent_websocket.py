"""Open a client WebSocket to the sandbox agent **via** the API proxy (E2B drop-in).

Requires optional install: ``pip install 'my-sandbox-sdk[ws]'`` (brings in ``websockets``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .ws_util import append_query_param


def _require_websockets():
    try:
        import websockets  # noqa: F401
    except ImportError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "Agent WebSocket support requires websockets "
            "(pip install 'my-sandbox-sdk[ws]' or pip install websockets)"
        ) from exc


def _uri_and_headers(
    ws_url: str, traffic_access_token: str, *, use_query_token: bool
) -> Tuple[str, Optional[Dict[str, str]]]:
    if use_query_token:
        return append_query_param(ws_url, "traffic_token", traffic_access_token), None
    return ws_url, {"e2b-traffic-access-token": traffic_access_token}


def open_agent_websocket_async(
    ws_url: str,
    traffic_access_token: str,
    *,
    use_query_token: bool = False,
    **kwargs: Any,
):
    """Return ``websockets.connect(...)`` async context manager (use ``async with``)."""
    _require_websockets()
    import websockets

    uri, headers = _uri_and_headers(ws_url, traffic_access_token, use_query_token=use_query_token)
    kw: Dict[str, Any] = dict(
        ping_interval=kwargs.pop("ping_interval", 20),
        ping_timeout=kwargs.pop("ping_timeout", 120),
        close_timeout=kwargs.pop("close_timeout", 10),
        max_size=kwargs.pop("max_size", None),
    )
    kw.update(kwargs)
    if headers:
        return websockets.connect(uri, additional_headers=headers, **kw)
    return websockets.connect(uri, **kw)


def open_agent_websocket_sync(
    ws_url: str,
    traffic_access_token: str,
    *,
    use_query_token: bool = False,
    **kwargs: Any,
):
    """Return a **synchronous** WebSocket client CM (use ``with``). Requires ``websockets`` 12+."""
    _require_websockets()
    try:
        from websockets.sync.client import connect as sync_connect
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Synchronous agent WebSocket requires websockets>=12 "
            "(pip install 'my-sandbox-sdk[ws]'). Python 3.8+ recommended."
        ) from exc

    uri, headers = _uri_and_headers(ws_url, traffic_access_token, use_query_token=use_query_token)
    kw: Dict[str, Any] = dict(
        ping_interval=kwargs.pop("ping_interval", 20),
        ping_timeout=kwargs.pop("ping_timeout", 120),
        close_timeout=kwargs.pop("close_timeout", 10),
        max_size=kwargs.pop("max_size", None),
    )
    kw.update(kwargs)
    if headers:
        return sync_connect(uri, additional_headers=headers, **kw)
    return sync_connect(uri, **kw)
