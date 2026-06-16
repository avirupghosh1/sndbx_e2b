"""Small helpers for E2B-style agent WebSocket URLs (query vs header token)."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def append_query_param(url: str, key: str, value: str) -> str:
    """Return ``url`` with query ``key=value`` set (replaces existing ``key``)."""
    p = urlparse(url)
    pairs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k != key]
    pairs.append((key, value))
    return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(pairs), p.fragment))
