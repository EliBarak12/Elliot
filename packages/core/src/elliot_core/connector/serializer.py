from __future__ import annotations

from elliot_core.errors import ElliotError
from elliot_core.types.connector import ConnectorConfig


def serialize_connector(config: ConnectorConfig) -> str:
    return config.model_dump_json(indent=2)


def deserialize_connector(json_str: str) -> ConnectorConfig:
    try:
        return ConnectorConfig.model_validate_json(json_str)
    except Exception as exc:
        raise ElliotError("INVALID_CONNECTOR", str(exc)) from exc
