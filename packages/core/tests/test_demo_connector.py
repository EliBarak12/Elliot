"""Regression gate for the shipped demo connector (task 081).

The demo connector is the first thing a new user sees and the canonical
example in the docs, so it must stay exemplary: valid schema, zero lint
findings of any severity, and tool coverage for every case in its bundled
eval suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from elliot_core.linter import lint_connector
from elliot_core.types import ConnectorConfig

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONNECTOR_PATH = _REPO_ROOT / "connectors" / "my-saas.connector.json"
_EVAL_PATH = _REPO_ROOT / "connectors" / "my-saas.eval.yaml"


@pytest.fixture(scope="module")
def demo_connector() -> ConnectorConfig:
    return ConnectorConfig.model_validate(json.loads(_CONNECTOR_PATH.read_text()))


def test_demo_connector_file_exists() -> None:
    assert _CONNECTOR_PATH.exists(), "the demo connector must ship in connectors/"


def test_demo_connector_lints_perfectly_clean(demo_connector: ConnectorConfig) -> None:
    issues = lint_connector(demo_connector)
    assert issues == [], "the demo connector must lint with zero findings, got: " + "; ".join(
        f"{i.severity} {i.code} ({i.tool_id})" for i in issues
    )


def test_demo_connector_data_files_ship(demo_connector: ConnectorConfig) -> None:
    for source in demo_connector.sources:
        assert source.type == "file"
        assert source.path is not None
        assert (_REPO_ROOT / source.path).exists(), f"missing data file: {source.path}"


def test_demo_connector_covers_its_eval_suite(demo_connector: ConnectorConfig) -> None:
    suite = yaml.safe_load(_EVAL_PATH.read_text())
    assert suite["connector"] == demo_connector.slug
    tool_ids = {tool.id for tool in demo_connector.tools}
    eval_tool_ids = {case["tool_id"] for case in suite["cases"]}
    missing = eval_tool_ids - tool_ids
    assert not missing, f"eval suite references tools the connector lacks: {sorted(missing)}"


def test_demo_connector_shows_the_signature_moves(demo_connector: ConnectorConfig) -> None:
    """The demo doubles as the reference example: it must demonstrate a
    cross-source JOIN, a bounded list, and at least one prose skill."""
    overview = next(t for t in demo_connector.tools if t.id == "get_customer_overview")
    assert set(overview.source_ids) == {"customers", "events"}

    list_tool = next(t for t in demo_connector.tools if t.id == "list_customers")
    assert any(p.name == "limit" and p.default is not None for p in list_tool.parameters)

    assert demo_connector.skills, "the demo must ship at least one skill"
    assert all(s.instructions or s.steps for s in demo_connector.skills)
