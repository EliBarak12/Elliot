"""Resolve {{ env:VAR_NAME }} placeholders in connector config."""

from __future__ import annotations

import os
import re
from typing import Any

from elliot_core.errors import ElliotError

_PLACEHOLDER = re.compile(r"\{\{\s*env:([A-Z0-9_]+)\s*\}\}")


class SecretResolutionError(ElliotError):
    """Raised when a required env var placeholder cannot be resolved.

    CLAUDE.md mandates every Elliot exception inherit from ElliotError so
    the error contract is uniform. Code: ``SECRET_NOT_SET``.
    """

    def __init__(self, var_name: str) -> None:
        # Deliberately do NOT include the env value or any other secret-
        # adjacent data — only the variable name and a fix-it hint.
        super().__init__(
            "SECRET_NOT_SET",
            f"Required secret '{{{{ env:{var_name} }}}}' is not set in environment",
            detail={"var_name": var_name},
        )
        self.var_name = var_name


def resolve_secrets(obj: Any) -> Any:
    """
    Recursively replace every {{ env:VAR_NAME }} placeholder with the
    corresponding env var value. Raises SecretResolutionError for missing vars.
    """
    if isinstance(obj, str):

        def _replace(match: re.Match[str]) -> str:
            name = match.group(1)
            val = os.environ.get(name)
            if val is None:
                raise SecretResolutionError(name)
            return val

        return _PLACEHOLDER.sub(_replace, obj)
    if isinstance(obj, dict):
        return {k: resolve_secrets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_secrets(item) for item in obj]
    return obj


def check_secrets(obj: Any) -> list[str]:
    """
    Return names of all {{ env:VAR }} placeholders in obj whose env var is NOT set.
    Used by the CLI `elliot secrets check` command.
    """
    missing: list[str] = []
    _collect(obj, missing)
    return missing


def _collect(obj: Any, missing: list[str]) -> None:
    if isinstance(obj, str):
        for m in _PLACEHOLDER.finditer(obj):
            name = m.group(1)
            if os.environ.get(name) is None:
                missing.append(name)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect(v, missing)
    elif isinstance(obj, list):
        for item in obj:
            _collect(item, missing)
