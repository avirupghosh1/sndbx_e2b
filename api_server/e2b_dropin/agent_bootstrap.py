"""Start ``agentlib-e2b-server`` inside Docker sandboxes at create time.

``ContainerManager.create_container`` always runs ``/bin/bash``, which overrides the
image ``CMD ["agentlib-e2b-server"]``. When E2B drop-in publishes the agent port,
the API must spawn the guest WebSocket server the same way it starts envd on :49983.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def container_has_agentlib_e2b_server(
    run_command: Callable[..., Any],
    container_id: str,
    *,
    timeout: float = 10.0,
) -> bool:
    r = run_command(
        container_id,
        "if command -v agentlib-e2b-server >/dev/null 2>&1; then echo __AGENTLIB_E2B__; else echo __NO_AGENTLIB_E2B__; fi",
        timeout=timeout,
    )
    out = (r.get("stdout") or "").strip()
    return "__AGENTLIB_E2B__" in out and int(r.get("exit_code") or 0) == 0


def agentlib_e2b_start_script(port: int) -> str:
    """Background ``agentlib-e2b-server`` and wait until localhost accepts TCP."""
    p = max(1, min(65535, int(port)))
    return f"""set -eu
: > /tmp/agentlib-e2b.log
if command -v agentlib-e2b-server >/dev/null 2>&1; then
  cmd=agentlib-e2b-server
elif test -x /usr/local/bin/agentlib-e2b-server; then
  cmd=/usr/local/bin/agentlib-e2b-server
else
  echo "agentlib-e2b-server not found in PATH" >&2
  exit 2
fi
if command -v setsid >/dev/null 2>&1; then
  setsid -f "$cmd" >>/tmp/agentlib-e2b.log 2>&1 &
else
  nohup "$cmd" >>/tmp/agentlib-e2b.log 2>&1 &
fi
for i in $(seq 1 60); do
  python3 -c "import socket; s=socket.socket(); import sys; r=s.connect_ex(('127.0.0.1',{p})); sys.exit(0 if r==0 else 1)" 2>/dev/null && exit 0
  sleep 0.25
done
echo "--- /tmp/agentlib-e2b.log ---" >&2
cat /tmp/agentlib-e2b.log 2>/dev/null || true
exit 1
"""
