"""Tests for elliot_core.cli (lint and eval subcommands)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elliot_core.types import ConnectorConfig

GOOD_CONNECTOR = {
    "name": "Test",
    "slug": "test",
    "version": "1.0.0",
    "sources": [],
    "tools": [
        {
            "id": "list_items",
            "name": "List Items",
            "description": "Return all items from the items table",
            "category": "READ",
            "source_ids": [],
            "sql": "SELECT id, name FROM items WHERE (:f IS NULL OR name = :f) LIMIT 50",
            "parameters": [
                {
                    "name": "filter_name",
                    "type": "string",
                    "required": False,
                    "description": "Filter by item name",
                }
            ],
        }
    ],
    "skills": [],
}

BAD_CONNECTOR = {
    "name": "Bad",
    "slug": "bad",
    "version": "1.0.0",
    "sources": [],
    "tools": [
        {
            "id": "x",
            "name": "X",
            "description": "Bad",  # too short
            "category": "READ",
            "source_ids": [],
            "sql": "SELECT * FROM items",  # unbounded
            "parameters": [],
        }
    ],
    "skills": [],
}


def _write_connector(tmp_path: Path, data: dict) -> Path:  # type: ignore[type-arg]
    p = tmp_path / "test.connector.json"
    p.write_text(json.dumps(data))
    return p


# ---------------------------------------------------------------------------
# _load_connector helper
# ---------------------------------------------------------------------------


def test_load_connector_valid(tmp_path: Path) -> None:
    from elliot_core.cli import _load_connector

    p = _write_connector(tmp_path, GOOD_CONNECTOR)
    config = _load_connector(str(p))
    assert isinstance(config, ConnectorConfig)
    assert config.slug == "test"


def test_load_connector_missing_file_exits(tmp_path: Path) -> None:
    from elliot_core.cli import _load_connector

    with pytest.raises(SystemExit):
        _load_connector(str(tmp_path / "nonexistent.json"))


# ---------------------------------------------------------------------------
# _cmd_lint via argparse simulation
# ---------------------------------------------------------------------------


def test_cmd_lint_clean_connector_exits_0(tmp_path: Path) -> None:
    import argparse

    from elliot_core.cli import _cmd_lint

    p = _write_connector(tmp_path, GOOD_CONNECTOR)
    args = argparse.Namespace(path=str(p))
    with pytest.raises(SystemExit) as exc_info:
        _cmd_lint(args)
    assert exc_info.value.code == 0


def test_cmd_lint_bad_connector_exits_1(tmp_path: Path) -> None:
    import argparse

    from elliot_core.cli import _cmd_lint

    p = _write_connector(tmp_path, BAD_CONNECTOR)
    args = argparse.Namespace(path=str(p))
    with pytest.raises(SystemExit) as exc_info:
        _cmd_lint(args)
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# main() dispatch
# ---------------------------------------------------------------------------


def test_main_no_command_exits_1(monkeypatch) -> None:
    import sys

    from elliot_core.cli import main

    monkeypatch.setattr(sys, "argv", ["elliot"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_main_lint_clean_exits_0(tmp_path: Path, monkeypatch) -> None:
    import sys

    from elliot_core.cli import main

    p = _write_connector(tmp_path, GOOD_CONNECTOR)
    monkeypatch.setattr(sys, "argv", ["elliot", "lint", str(p)])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_main_lint_bad_exits_1(tmp_path: Path, monkeypatch) -> None:
    import sys

    from elliot_core.cli import main

    p = _write_connector(tmp_path, BAD_CONNECTOR)
    monkeypatch.setattr(sys, "argv", ["elliot", "lint", str(p)])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
