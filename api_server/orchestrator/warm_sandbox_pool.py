"""Pre-provisioned Docker sandboxes to hide cold-start latency (image pull + container create).

When ``SANDBOX_WARM_POOL_SIZE > 0`` and runtime is **docker**, one or more **pool segments**
run in the background. Each segment is keyed by ``(logical template_id, cpu, memory, timeout)``
and may provision from a **warm snapshot image** (custom templates) or from the base image
(default ``SANDBOX_WARM_POOL_TEMPLATE_ID`` profile).

See ``docs/CUSTOM_TEMPLATES.md`` for custom templates + snapshot-backed warm pools.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any, Deque, Dict, Optional, Set, Tuple

if TYPE_CHECKING:
    from config import Config
    from .sandbox_manager import SandboxManager

logger = logging.getLogger(__name__)

PoolKey = Tuple[str, str, str, int]


class WarmSandboxPool:
    """Maintains ``pool_size`` idle sandboxes for one (template_id, cpu, mem, timeout) profile."""

    def __init__(
        self,
        manager: "SandboxManager",
        *,
        logical_template_id: str,
        cpu_limit: str,
        memory_limit: str,
        timeout: int,
        pool_size: int,
        from_snapshot_image: Optional[str] = None,
    ):
        self._manager = manager
        self._logical_template_id = logical_template_id.strip()
        self._cpu = str(cpu_limit)
        self._mem = str(memory_limit)
        self._timeout = int(timeout)
        self._size = max(0, int(pool_size))
        self._from_snapshot = (from_snapshot_image or "").strip() or None
        self._lock = threading.Lock()
        self._available: Deque[str] = deque()
        self._warm_ids: Set[str] = set()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def pool_key(self) -> PoolKey:
        return (self._logical_template_id, self._cpu, self._mem, self._timeout)

    def start(self) -> None:
        if self._size <= 0:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"warm-pool-{self._logical_template_id[:16]}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Warm pool segment started: target=%s template_id=%r snap=%r cpu=%s mem=%s timeout=%s",
            self._size,
            self._logical_template_id,
            self._from_snapshot,
            self._cpu,
            self._mem,
            self._timeout,
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        with self._lock:
            ids = list(self._available)
            self._available.clear()
            self._warm_ids.clear()
        for sid in ids:
            try:
                self._manager.kill_sandbox(sid)
            except Exception as ex:  # noqa: BLE001
                logger.warning("Warm pool shutdown: failed to kill %s: %s", sid, ex)

    def discard(self, sandbox_id: str) -> None:
        with self._lock:
            try:
                self._available.remove(sandbox_id)
            except ValueError:
                pass
            self._warm_ids.discard(sandbox_id)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "template_id": self._logical_template_id,
                "target_size": self._size,
                "ready": len(self._available),
                "from_snapshot_image": self._from_snapshot,
                "cpu_limit": self._cpu,
                "memory_limit": self._mem,
                "timeout": self._timeout,
            }

    def try_acquire(
        self,
        template_id: str,
        metadata: Optional[Dict[str, Any]],
        cpu_limit: str,
        memory_limit: str,
        timeout: int,
    ) -> Optional[str]:
        if self._size <= 0:
            return None
        if template_id.strip() != self._logical_template_id:
            return None
        if str(cpu_limit) != self._cpu or str(memory_limit) != self._mem or int(timeout) != int(self._timeout):
            return None
        with self._lock:
            if not self._available:
                return None
            sid = self._available.popleft()
            self._warm_ids.discard(sid)
        merged = dict(metadata or {})
        merged.pop("_warm_pool", None)
        base = self._manager.get_sandbox(sid)
        if base:
            prev = dict(base.get("metadata") or {})
            prev.pop("_warm_pool", None)
            merged = {**prev, **merged}
        self._manager.db.merge_sandbox_metadata(sid, merged)
        logger.info("Warm pool: handed sandbox %s (template=%s)", sid, self._logical_template_id)
        return sid

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._top_up()
            except Exception as ex:  # noqa: BLE001
                logger.exception("Warm pool top-up error: %s", ex)
            time.sleep(1.5)

    def _top_up(self) -> None:
        with self._lock:
            need = self._size - len(self._available)
        for _ in range(need):
            if self._stop.is_set():
                break
            sid = self._manager._create_sandbox_fresh(
                template_id=self._logical_template_id,
                metadata={"_warm_pool": True},
                cpu_limit=self._cpu,
                memory_limit=self._mem,
                timeout=self._timeout,
                from_snapshot_image=self._from_snapshot,
            )
            if not sid:
                logger.warning("Warm pool: failed to provision (template=%s)", self._logical_template_id)
                break
            with self._lock:
                self._available.append(sid)
                self._warm_ids.add(sid)
            with self._lock:
                nready = len(self._available)
            logger.info(
                "Warm pool: provisioned %s for template=%s (ready=%s)",
                sid,
                self._logical_template_id,
                nready,
            )


class MultiWarmSandboxPool:
    """One ``WarmSandboxPool`` segment per distinct (template_id, cpu, mem, timeout) profile."""

    def __init__(self, manager: "SandboxManager", config: "Config"):
        self._manager = manager
        self._cfg = config
        self._size = max(0, int(config.SANDBOX_WARM_POOL_SIZE))
        self._pools: Dict[PoolKey, WarmSandboxPool] = {}
        self._pools_lock = threading.Lock()

    def start(self) -> None:
        if self._size <= 0:
            return
        tid = (self._cfg.SANDBOX_WARM_POOL_TEMPLATE_ID or self._cfg.DEFAULT_TEMPLATE).strip()
        self.ensure_pool_for(
            tid,
            self._cfg.SANDBOX_WARM_POOL_CPU or self._cfg.DEFAULT_CPU_LIMIT,
            self._cfg.SANDBOX_WARM_POOL_MEMORY or self._cfg.DEFAULT_MEMORY_LIMIT,
            int(self._cfg.SANDBOX_WARM_POOL_TIMEOUT or self._cfg.DEFAULT_TIMEOUT),
            from_snapshot_image=None,
        )

    def ensure_pool_for(
        self,
        logical_template_id: str,
        cpu_limit: str,
        memory_limit: str,
        timeout: int,
        from_snapshot_image: Optional[str],
    ) -> None:
        if self._size <= 0:
            return
        key: PoolKey = (
            logical_template_id.strip(),
            str(cpu_limit),
            str(memory_limit),
            int(timeout),
        )
        with self._pools_lock:
            if key in self._pools:
                return
            pool = WarmSandboxPool(
                self._manager,
                logical_template_id=key[0],
                cpu_limit=key[1],
                memory_limit=key[2],
                timeout=key[3],
                pool_size=self._size,
                from_snapshot_image=from_snapshot_image,
            )
            self._pools[key] = pool
        pool.start()

    def try_acquire(
        self,
        template_id: str,
        metadata: Optional[Dict[str, Any]],
        cpu_limit: str,
        memory_limit: str,
        timeout: int,
    ) -> Optional[str]:
        key: PoolKey = (
            template_id.strip(),
            str(cpu_limit),
            str(memory_limit),
            int(timeout),
        )
        with self._pools_lock:
            pool = self._pools.get(key)
        if pool is None:
            return None
        return pool.try_acquire(template_id, metadata, cpu_limit, memory_limit, timeout)

    def discard(self, sandbox_id: str) -> None:
        with self._pools_lock:
            pools = list(self._pools.values())
        for p in pools:
            p.discard(sandbox_id)

    def stop(self, timeout: float = 5.0) -> None:
        with self._pools_lock:
            pools = list(self._pools.values())
            self._pools.clear()
        for p in pools:
            p.stop(timeout=timeout)

    def stats(self) -> dict[str, Any]:
        with self._pools_lock:
            pools = list(self._pools.values())
        return {
            "enabled": self._size > 0,
            "target_per_pool": self._size,
            "segments": [p.stats() for p in pools],
        }
