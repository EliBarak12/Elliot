"""Rate limiter factory used by both mcp-plugin and connector-runtime."""

from __future__ import annotations

import os
from typing import Any


def build_limiter() -> Any:
    """Return a slowapi Limiter using the ELLIOT_RATE_LIMIT env var.

    Default: 120/minute. Set ELLIOT_RATE_LIMIT=30/minute to restrict further.
    """
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    default_limit = os.environ.get("ELLIOT_RATE_LIMIT", "120/minute")
    return Limiter(key_func=get_remote_address, default_limits=[default_limit])
