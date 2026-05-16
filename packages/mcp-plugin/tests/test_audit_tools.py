"""Tests for the connector audit MCP tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_core.types import ConnectorConfig
from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.audit_tools import register_audit_tools


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    server = FastMCP("test")
    register_audit_tools(server, session)
    return server


@pytest.fixture(autouse=True)
def _audit_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.audit_tools.AUDIT_RESULTS_DIR",
        str(tmp_path / ".elliot" / "audit-results"),
    )


def _tool(mcp: FastMCP, name: str):  # type: ignore[no-untyped-def]
    return mcp._tool_manager._tools[name].fn


def _connector() -> ConnectorConfig:
    return ConnectorConfig(
        name="Acme",
        slug="acme",
        version="1.0.0",
        tools=[
            {
                "id": "list_customers",
                "name": "List Customers",
                "description": "Return all customers for agents",
                "category": "READ",
                "sql": "SELECT id FROM customers LIMIT 20",
                "parameters": [],
            }
        ],  # type: ignore[arg-type]
    )


def _transcript(seed_id: str = "seed-1", *, completed: bool = True) -> str:
    return json.dumps(
        {
            "seed_id": seed_id,
            "task": "do the thing",
            "agent_label": "auditor-1",
            "task_completed": completed,
            "summary": "done",
            "calls": [
                {
                    "tool_id": "list_customers",
                    "arguments": {},
                    "ok": True,
                    "result_row_count": 3,
                    "result_token_estimate": 150,
                }
            ],
        }
    )


def test_generate_seeds_no_connector(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_generate_audit_seeds")()
    assert "text" in result or "error" in result


def test_generate_seeds_with_connector(mcp: FastMCP, session: ElliotSession) -> None:
    session.connector = _connector()
    result = _tool(mcp, "elliot_generate_audit_seeds")(count=3)
    assert result["seed_count"] >= 1
    assert "rubric" in result
    assert "instructions" in result


def test_submit_transcript(mcp: FastMCP, session: ElliotSession) -> None:
    result = _tool(mcp, "elliot_submit_audit_transcript")(_transcript())
    assert result["status"] == "submitted"
    assert result["calls_recorded"] == 1
    assert len(session.audit_transcripts) == 1


def test_submit_transcript_invalid_json(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_submit_audit_transcript")("{bad")
    assert "text" in result or "error" in result


def test_submit_transcript_invalid_shape(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_submit_audit_transcript")(json.dumps({"calls": "nope"}))
    assert "text" in result or "error" in result


def test_list_and_clear_transcripts(mcp: FastMCP) -> None:
    _tool(mcp, "elliot_submit_audit_transcript")(_transcript())
    listed = _tool(mcp, "elliot_list_audit_transcripts")()
    assert listed["count"] == 1
    cleared = _tool(mcp, "elliot_clear_audit_transcripts")()
    assert cleared["cleared"] == 1
    assert _tool(mcp, "elliot_list_audit_transcripts")()["count"] == 0


def test_judge_no_connector(mcp: FastMCP) -> None:
    _tool(mcp, "elliot_submit_audit_transcript")(_transcript())
    result = _tool(mcp, "elliot_judge_audit")()
    assert "text" in result or "error" in result


def test_judge_no_transcripts(mcp: FastMCP, session: ElliotSession) -> None:
    session.connector = _connector()
    result = _tool(mcp, "elliot_judge_audit")()
    assert "text" in result or "error" in result


def test_judge_produces_report(mcp: FastMCP, session: ElliotSession) -> None:
    session.connector = _connector()
    _tool(mcp, "elliot_submit_audit_transcript")(_transcript())
    result = _tool(mcp, "elliot_judge_audit")()
    assert result["passed"] is True
    assert result["connector_slug"] == "acme"
    assert "report_path" in result
    assert Path(result["report_path"]).exists()


def test_judge_flags_failed_task(mcp: FastMCP, session: ElliotSession) -> None:
    session.connector = _connector()
    _tool(mcp, "elliot_submit_audit_transcript")(_transcript(completed=False))
    result = _tool(mcp, "elliot_judge_audit")()
    assert result["passed"] is False
    assert result["findings"]
