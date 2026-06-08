"""Environment-variable helpers shared across Elliot services."""

from __future__ import annotations

import os

# Strings accepted as an affirmative boolean flag, case-insensitive. Centralised
# so every ELLIOT_* feature flag is parsed identically across all packages.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_truthy(value: str | None) -> bool:
    """Return True when ``value`` is an affirmative flag (1/true/yes/on)."""
    return (value or "").strip().lower() in _TRUTHY


def env_flag(name: str, *, default: bool = False) -> bool:
    """Read a boolean feature flag from the environment.

    Accepts 1/true/yes/on (case-insensitive) as True. An unset or blank
    variable yields ``default``; any other value is False.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return is_truthy(raw)
