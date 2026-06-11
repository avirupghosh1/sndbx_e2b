"""Configuration."""

import os
from typing import Optional

class Config:
    """Application configuration."""

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8000))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    
    # API
    API_KEY: str = os.getenv("API_KEY", "test-key-12345")
    API_TITLE: str = "Sandbox API Server"
    API_VERSION: str = "1.0.0"
    API_DESCRIPTION: str = "REST API server for managing sandboxes and agents"
    
    # Database
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "sandboxes.db")

    # Sandbox VM engine: ``docker`` (default: Docker Engine + optional gVisor) or ``firecracker`` (KVM microVMs).
    SANDBOX_ENGINE: str = os.getenv("SANDBOX_ENGINE", "docker").strip().lower()

    # Docker
    DOCKER_HOST: Optional[str] = os.getenv("DOCKER_HOST", None)  # e.g. ssh://user@linux-vm — see docs/REMOTE_SANDBOX_VM.md
    
    # Sandbox defaults
    DEFAULT_TEMPLATE: str = os.getenv("DEFAULT_TEMPLATE", "python:3.11")
    DEFAULT_CPU_LIMIT: str = os.getenv("DEFAULT_CPU_LIMIT", "1")
    DEFAULT_MEMORY_LIMIT: str = os.getenv("DEFAULT_MEMORY_LIMIT", "512m")
    DEFAULT_TIMEOUT: int = int(os.getenv("DEFAULT_TIMEOUT", 3600))

    # Warm pool: pre-create sandboxes matching this profile for faster POST /sandboxes (Docker or Firecracker engine).
    SANDBOX_WARM_POOL_SIZE: int = int(os.getenv("SANDBOX_WARM_POOL_SIZE", "0"))
    SANDBOX_WARM_POOL_TEMPLATE_ID: str = os.getenv(
        "SANDBOX_WARM_POOL_TEMPLATE_ID",
        os.getenv("DEFAULT_TEMPLATE", "python:3.11"),
    )
    SANDBOX_WARM_POOL_CPU: str = os.getenv("SANDBOX_WARM_POOL_CPU", os.getenv("DEFAULT_CPU_LIMIT", "1"))
    SANDBOX_WARM_POOL_MEMORY: str = os.getenv(
        "SANDBOX_WARM_POOL_MEMORY", os.getenv("DEFAULT_MEMORY_LIMIT", "512m")
    )
    SANDBOX_WARM_POOL_TIMEOUT: int = int(
        os.getenv("SANDBOX_WARM_POOL_TIMEOUT", os.getenv("DEFAULT_TIMEOUT", "3600"))
    )

    # Docker ``docker commit`` repository prefix for POST /sandboxes/{id}/snapshot (local image names)
    SANDBOX_SNAPSHOT_REPO: str = os.getenv("SANDBOX_SNAPSHOT_REPO", "mysandbox-snap")

    # One-time custom template build (base image + start_cmd + settle) before ``docker commit``
    TEMPLATE_BUILD_CPU: str = os.getenv("TEMPLATE_BUILD_CPU", "2")
    TEMPLATE_BUILD_MEMORY: str = os.getenv("TEMPLATE_BUILD_MEMORY", "2g")

    # Linux container isolation (Docker Engine):
    # - ``docker`` (default): daemon default OCI runtime (typically ``runc``).
    # - ``gvisor``: use ``runsc`` (gVisor) — runtime must be registered on the daemon (``docker info``).
    # Non-empty ``SANDBOX_DOCKER_OCI_RUNTIME`` overrides ``SANDBOX_ISOLATION`` for the OCI name.
    SANDBOX_ISOLATION: str = os.getenv("SANDBOX_ISOLATION", "docker").strip().lower()
    SANDBOX_DOCKER_OCI_RUNTIME: str = os.getenv("SANDBOX_DOCKER_OCI_RUNTIME", "").strip()

    def docker_oci_runtime(self) -> Optional[str]:
        """Return ``runsc`` for gVisor-backed sandboxes, or ``None`` for default ``runc``."""
        import logging

        log = logging.getLogger(__name__)
        raw = (self.SANDBOX_DOCKER_OCI_RUNTIME or "").strip().lower()
        if raw:
            if raw == "runsc":
                return "runsc"
            if raw in ("runc", "default", "docker"):
                return None
            log.warning(
                "SANDBOX_DOCKER_OCI_RUNTIME=%r unknown; use runsc, runc, or leave empty. Using default.",
                self.SANDBOX_DOCKER_OCI_RUNTIME,
            )
            return None
        iso = (self.SANDBOX_ISOLATION or "docker").strip().lower()
        if iso in ("gvisor", "runsc", "gv"):
            return "runsc"
        return None

    # --- Firecracker (only when ``SANDBOX_ENGINE=firecracker``; Linux + KVM + tap + SSH rootfs) ---
    FIRECRACKER_BINARY: str = os.getenv("FIRECRACKER_BINARY", "/usr/local/bin/firecracker").strip()
    FIRECRACKER_KERNEL: str = os.getenv("FIRECRACKER_KERNEL", "").strip()
    FIRECRACKER_ROOTFS: str = os.getenv("FIRECRACKER_ROOTFS", "").strip()
    FIRECRACKER_GATEWAY: str = os.getenv("FIRECRACKER_GATEWAY", "172.16.0.1").strip()
    FIRECRACKER_SUBNET_PREFIX: str = os.getenv("FIRECRACKER_SUBNET_PREFIX", "172.16.0").strip()
    FIRECRACKER_GUEST_OCTET_BASE: int = int(os.getenv("FIRECRACKER_GUEST_OCTET_BASE", "10"))
    FIRECRACKER_TAP_PATTERN: str = os.getenv("FIRECRACKER_TAP_PATTERN", "tapfc{slot}").strip()
    FIRECRACKER_TAP_SLOTS: int = int(os.getenv("FIRECRACKER_TAP_SLOTS", "8"))
    FIRECRACKER_SSH_USER: str = os.getenv("FIRECRACKER_SSH_USER", "root").strip()
    FIRECRACKER_SSH_KEY: str = os.getenv("FIRECRACKER_SSH_KEY", "").strip()
    FIRECRACKER_SSH_KNOWN_HOSTS: str = os.getenv("FIRECRACKER_SSH_KNOWN_HOSTS", "/dev/null").strip()
    FIRECRACKER_ENABLE_PCI: str = os.getenv("FIRECRACKER_ENABLE_PCI", "false").strip()

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def get_config() -> Config:
    """Get configuration."""
    return Config()
