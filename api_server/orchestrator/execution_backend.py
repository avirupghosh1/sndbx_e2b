"""Construct the sandbox execution plane: Docker Engine (optional gVisor) or Firecracker microVMs."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from .container_manager import ContainerManager
from .protocols import SandboxExecutionPlane

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)


def build_execution_backend(config: "Config | None" = None) -> SandboxExecutionPlane:
    """Return Docker ``ContainerManager`` or ``FirecrackerVmmPlane`` based on ``SANDBOX_ENGINE``."""
    if config is None:
        from config import get_config

        config = get_config()
    engine = (getattr(config, "SANDBOX_ENGINE", None) or "docker").strip().lower()
    if engine in ("firecracker", "fc", "microvm"):
        from .firecracker_plane import FirecrackerVmmPlane

        logger.info("Sandbox execution: Firecracker microVMs (SANDBOX_ENGINE=%s)", engine)
        return FirecrackerVmmPlane(config)

    oci = config.docker_oci_runtime()
    # docker-py ``from_env()`` reads ``DOCKER_HOST`` / TLS env from the process environment.
    # Sync from Config so a single source (env or ``.env`` via ``main``) reliably targets a remote VM daemon.
    dh = (getattr(config, "DOCKER_HOST", None) or "").strip()
    if dh:
        os.environ["DOCKER_HOST"] = dh
        logger.info("Docker client will use DOCKER_HOST from configuration")
    if oci:
        logger.info("Sandbox execution: Docker Engine + gVisor (oci_runtime=%s)", oci)
    else:
        logger.info("Sandbox execution: Docker Engine (default OCI runtime, typically runc)")
    return ContainerManager(oci_runtime=oci)
