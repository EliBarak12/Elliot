"""Load and discover ConnectorConfig files from disk."""

from __future__ import annotations

import json
from pathlib import Path

from elliot_core.types.connector import ConnectorConfig


class ConnectorLoadError(Exception):
    pass


def load_connector(path: str | Path) -> ConnectorConfig:
    p = Path(path)
    if not p.exists():
        raise ConnectorLoadError(f"Connector file not found: {p}")
    if p.suffix != ".json":
        raise ConnectorLoadError(f"Expected .json file, got: {p.suffix}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConnectorLoadError(f"Invalid JSON in {p}: {exc}") from exc
    try:
        return ConnectorConfig.model_validate(data)
    except Exception as exc:
        raise ConnectorLoadError(f"Schema validation failed for {p}: {exc}") from exc


def discover_connectors(directory: str | Path) -> list[Path]:
    """Return sorted list of *.connector.json paths under directory."""
    d = Path(directory)
    if not d.is_dir():
        return []
    return sorted(d.rglob("*.connector.json"))
