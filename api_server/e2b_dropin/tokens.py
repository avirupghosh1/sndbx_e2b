"""HMAC-signed tokens for ``e2b-traffic-access-token`` (edge-style auth without E2B cloud)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional


def mint_traffic_token(
    secret: str,
    *,
    sandbox_id: str,
    agent_port: int,
    ttl_sec: int,
) -> str:
    """Return URL-safe token encoding sandbox_id, port, and expiry."""
    if not (secret or "").strip():
        raise ValueError("E2B_DROPIN_WS_SECRET must be set to mint traffic tokens")
    exp = int(time.time()) + max(60, int(ttl_sec))
    payload: Dict[str, Any] = {"sid": (sandbox_id or "").strip(), "p": int(agent_port), "exp": exp}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
        + "."
        + base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    )


def verify_traffic_token(secret: str, token: str) -> Optional[Dict[str, Any]]:
    """Verify token; return payload dict or None."""
    if not token or not (secret or "").strip():
        return None
    try:
        if "." not in token:
            return None
        body_b64, sig_b64 = token.split(".", 1)
        body = base64.urlsafe_b64decode(body_b64 + "=" * (-len(body_b64) % 4))
        sig = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
        expect = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expect):
            return None
        data = json.loads(body.decode("utf-8"))
        if int(data.get("exp") or 0) < int(time.time()):
            return None
        return data
    except (ValueError, OSError, json.JSONDecodeError, TypeError):
        return None
