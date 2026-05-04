from __future__ import annotations

import os
from pathlib import Path

from elliot_core.connector.serializer import deserialize_connector
from elliot_core.errors import ElliotError
from elliot_core.types.connector import ConnectorConfig

_ENV_PATH = "ELLIOT_CONNECTOR_PATH"
_ENV_JSON = "ELLIOT_CONNECTOR_JSON"
_SECRET_PREFIX = "ELLIOT_SECRET_"


def load_connector(path: str | None = None) -> ConnectorConfig:
    """Load ConnectorConfig from file path, env var path, or inline JSON."""
    if path:
        return _from_file(path)

    env_path = os.environ.get(_ENV_PATH)
    if env_path:
        return _from_file(env_path)

    env_json = os.environ.get(_ENV_JSON)
    if env_json:
        return deserialize_connector(env_json)

    raise ElliotError(
        "CONNECTOR_NOT_FOUND",
        f"Provide --connector <path>, or set {_ENV_PATH} / {_ENV_JSON}",
    )


def _from_file(path: str) -> ConnectorConfig:
    p = Path(path)
    if not p.exists():
        raise ElliotError("CONNECTOR_NOT_FOUND", f"Connector file not found: {path}")
    try:
        return deserialize_connector(p.read_text())
    except ElliotError:
        raise
    except Exception as exc:
        raise ElliotError("INVALID_CONNECTOR", f"Failed to read {path}: {exc}") from exc


def load_secrets(prefix: str = _SECRET_PREFIX) -> dict[str, str]:
    """Collect ELLIOT_SECRET_* env vars as a lowercase-keyed secrets dict."""
    return {
        k[len(prefix):].lower(): v
        for k, v in os.environ.items()
        if k.startswith(prefix)
    }
