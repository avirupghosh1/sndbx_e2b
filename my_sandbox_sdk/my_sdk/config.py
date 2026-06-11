"""
Configuration and utilities for My Sandbox SDK.
"""

import os
from typing import Optional

# Sandbox create can block on Docker image pulls; urllib client must wait long enough.
DEFAULT_SDK_REQUEST_TIMEOUT = 600.0


class Config:
    """Configuration for SDK."""
    
    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        request_timeout: float = DEFAULT_SDK_REQUEST_TIMEOUT,
    ):
        """
        Initialize configuration.
        
        Args:
            api_url: API server URL (can also be set via MY_SDK_API_URL env var)
            api_key: API key (can also be set via MY_SDK_API_KEY env var)
            request_timeout: Request timeout in seconds
        """
        self.api_url = api_url or os.getenv("MY_SDK_API_URL", "http://localhost:8000")
        self.api_key = api_key or os.getenv("MY_SDK_API_KEY")
        self.request_timeout = request_timeout
    
    def validate(self) -> bool:
        """Check if configuration is valid."""
        return bool(self.api_url)


def get_default_config() -> Config:
    """Get configuration from environment variables."""
    return Config(
        api_url=os.getenv("MY_SDK_API_URL"),
        api_key=os.getenv("MY_SDK_API_KEY"),
        request_timeout=float(os.getenv("MY_SDK_REQUEST_TIMEOUT", str(DEFAULT_SDK_REQUEST_TIMEOUT))),
    )
