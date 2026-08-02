"""Resolve {{ env:VAR_NAME }} placeholders in connector config."""

from __future__ import annotations

import os
import re
from typing import Any

from elliot_core.errors import ElliotError

_PLACEHOLDER = re.compile(r"\{\{\s*env:([A-Z0-9_]+)\s*\}\}")


def host_env_secrets_allowed() -> bool:
    """Whether a ``{{ env:NAME }}`` secret may fall back to the host process env.

    Local single-user Elliot keeps connector secrets in its own process
    environment, so reading ``os.environ`` is the intended resolution path.

    The multi-tenant cloud is different: it resolves each tenant's secrets into
    a closed map and sets ``ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS=1`` so a tenant
    connector can never declare ``{{ env:DATABASE_URL }}`` (or
    ``AWS_SECRET_ACCESS_KEY``, or the platform's own encryption key) and have
    the server inject its own environment into a tenant's request.
    """
    return os.environ.get("ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }


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
