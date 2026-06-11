#!/usr/bin/env python3
"""
Demonstrate two logical templates + warm pool refill + faster second creates.

Prerequisites (Docker runtime):
  - API running with SANDBOX_WARM_POOL_SIZE>=2 (e.g. export SANDBOX_WARM_POOL_SIZE=2
    before docker compose up — see api_server/docker-compose.yml).
  - Match pool profile on creates: default cpu=1, memory=512m, timeout=3600 (same as
    SANDBOX_WARM_POOL_* defaults unless you changed them).

Usage:
  export API_URL=http://127.0.0.1:8000
  export API_KEY=test-key-12345
  python examples/demo_two_templates_warm_pool.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.environ.get("API_KEY", "test-key-12345")

TPL_A = "demotpl_a"
TPL_B = "demotpl_b"

# Must match warm-pool segment key (defaults in CreateSandboxRequest / warm pool env)
CPU = "1"
MEM = "512m"
TIMEOUT = 3600


def _req(method: str, path: str, body: Optional[dict] = None) -> Tuple[int, Any]:
    url = f"{API_URL}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    r = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "X-API-Key": API_KEY,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(r, timeout=900.0) as resp:
            raw = resp.read().decode("utf-8")
            code = resp.status
            if not raw:
                return code, None
            return code, json.loads(raw)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8")
        try:
            parsed = json.loads(err)
        except json.JSONDecodeError:
            parsed = err
        return e.code, parsed


def health_warm_pool() -> Dict[str, Any]:
    code, data = _req("GET", "/health")
    if code != 200:
        raise RuntimeError(f"GET /health failed: {code} {data}")
    return (data or {}).get("warm_pool") or {}


def print_warm_pool_banner(label: str) -> None:
    wp = health_warm_pool()
    print(f"\n--- {label} ---")
    print(json.dumps(wp, indent=2))


def register_template(
    template_id: str,
    marker: str,
    settle_seconds: int = 8,
) -> None:
    body = {
        "template_id": template_id,
        "base_image": "python:3.11-slim",
        "env": {"DEMO_TEMPLATE_MARKER": marker},
        "start_cmd": f"bash -c 'mkdir -p /tmp && echo {marker} > /tmp/warm_demo_marker && sync'",
        "settle_seconds": settle_seconds,
    }
    code, data = _req("POST", "/templates", body)
    if code not in (200, 201):
        raise RuntimeError(f"POST /templates {template_id} failed: {code} {data}")


def create_sandbox(template_id: str) -> Tuple[str, float]:
    body = {
        "template_id": template_id,
        "cpu_limit": CPU,
        "memory_limit": MEM,
        "timeout": TIMEOUT,
        "metadata": {"demo": "warm_pool_script"},
    }
    t0 = time.perf_counter()
    code, data = _req("POST", "/sandboxes", body)
    elapsed = time.perf_counter() - t0
    if code not in (200, 201):
        raise RuntimeError(f"POST /sandboxes failed: {code} {data}")
    sid = (data or {}).get("sandbox_id")
    if not sid:
        raise RuntimeError(f"No sandbox_id in response: {data}")
    return str(sid), elapsed


def kill_sandbox(sandbox_id: str) -> None:
    code, data = _req("POST", f"/sandboxes/{sandbox_id}/kill", {})
    if code != 200:
        print(f"WARN: kill {sandbox_id} -> {code} {data}")


def segment_for(
    segments: List[Dict[str, Any]], template_id: str
) -> Optional[Dict[str, Any]]:
    for s in segments:
        if s.get("template_id") == template_id:
            return s
    return None


def wait_segments_ready(
    template_ids: Tuple[str, str],
    min_ready: int,
    timeout_sec: float = 180.0,
    poll: float = 2.0,
) -> None:
    deadline = time.time() + timeout_sec
    a, b = template_ids
    while time.time() < deadline:
        wp = health_warm_pool()
        segs = wp.get("segments") or []
        sa = segment_for(segs, a)
        sb = segment_for(segs, b)
        ra = (sa or {}).get("ready", 0)
        rb = (sb or {}).get("ready", 0)
        if sa is not None and sb is not None and ra >= min_ready and rb >= min_ready:
            print(
                f"\n(refill OK) segment {a} ready={ra}, "
                f"{b} ready={rb} (target each >= {min_ready})"
            )
            return
        print(
            f"  (waiting refill) {a} ready={ra} seg_found={sa is not None}, "
            f"{b} ready={rb} seg_found={sb is not None}"
        )
        time.sleep(poll)
    raise TimeoutError(
        f"Warm segments for {template_ids} did not reach ready>={min_ready} within {timeout_sec}s"
    )


def main() -> None:
    print("API_URL=", API_URL)
    print("Using templates:", TPL_A, TPL_B)
    print("Create profile (must match warm pool):", CPU, MEM, TIMEOUT)

    print_warm_pool_banner("Warm pool BEFORE registering templates")

    print("\n>> Register two logical templates (no build yet).")
    register_template(TPL_A, "marker-a", settle_seconds=8)
    register_template(TPL_B, "marker-b", settle_seconds=8)

    print_warm_pool_banner("Warm pool AFTER register (unchanged until first /sandboxes)")

    created: List[str] = []

    print(f"\n>> First sandbox for {TPL_A} (one-time snapshot build + create; slow).")
    print_warm_pool_banner("Warm pool BEFORE first create (template A)")
    sid_a1, t_a1 = create_sandbox(TPL_A)
    created.append(sid_a1)
    print(f"   sandbox_id={sid_a1}  elapsed={t_a1:.2f}s")
    print_warm_pool_banner("Warm pool AFTER first create (template A)")

    print(f"\n>> First sandbox for {TPL_B} (one-time snapshot build + create; slow).")
    print_warm_pool_banner("Warm pool BEFORE first create (template B)")
    sid_b1, t_b1 = create_sandbox(TPL_B)
    created.append(sid_b1)
    print(f"   sandbox_id={sid_b1}  elapsed={t_b1:.2f}s")
    print_warm_pool_banner("Warm pool AFTER first create (template B)")

    wp = health_warm_pool()
    target = int(wp.get("target_per_pool") or 0)
    if target <= 0:
        print(
            "\n*** SANDBOX_WARM_POOL_SIZE is 0 on the server: "
            "no warm segments; second creates still use snapshot but not pool handoff. "
            "Set SANDBOX_WARM_POOL_SIZE=2 and recreate the API container, then re-run. ***\n"
        )
        min_ready = 0
    else:
        min_ready = target
        print(
            f"\n>> Waiting for both segments to refill to ready>={min_ready} "
            f"(SANDBOX_WARM_POOL_SIZE={target})…"
        )
        try:
            wait_segments_ready((TPL_A, TPL_B), min_ready=min_ready, timeout_sec=240.0)
        except TimeoutError as e:
            print(f"WARN: {e}")
            min_ready = 0

    print("\n>> Second sandbox for each template (warm handoff when pool enabled + refilled).")
    print_warm_pool_banner("Warm pool BEFORE second create (template A)")
    sid_a2, t_a2 = create_sandbox(TPL_A)
    created.append(sid_a2)
    print(f"   sandbox_id={sid_a2}  elapsed={t_a2:.2f}s  (first A was {t_a1:.2f}s)")
    print_warm_pool_banner("Warm pool AFTER second create (template A)")

    print_warm_pool_banner("Warm pool BEFORE second create (template B)")
    sid_b2, t_b2 = create_sandbox(TPL_B)
    created.append(sid_b2)
    print(f"   sandbox_id={sid_b2}  elapsed={t_b2:.2f}s  (first B was {t_b1:.2f}s)")
    print_warm_pool_banner("Warm pool AFTER second create (template B)")

    print("\n>> Summary")
    print(f"   Template A: first {t_a1:.2f}s  second {t_a2:.2f}s")
    print(f"   Template B: first {t_b1:.2f}s  second {t_b2:.2f}s")

    print("\n>> Cleanup (kill demo sandboxes)")
    for sid in created:
        kill_sandbox(sid)
    print_warm_pool_banner("Warm pool AFTER kills (segments refill in background)")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print("ERROR:", ex, file=sys.stderr)
        sys.exit(1)
