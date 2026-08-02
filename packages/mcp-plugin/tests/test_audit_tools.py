"""Tests for the connector audit MCP tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elliot_core.mcp_compat import FastMCP
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
        "elliot_mcp_plugin.tools.audit_tools._audit_results_dir",
        lambda session: tmp_path / ".elliot" / "audit-results",
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


# ── LLM-judge tools ──────────────────────────────────────────────────────────


def test_request_llm_judgment_returns_brief(mcp: FastMCP, session: ElliotSession) -> None:
    session.connector = _connector()
    _tool(mcp, "elliot_submit_audit_transcript")(_transcript())
    brief = _tool(mcp, "elliot_request_llm_judgment")()
    assert "dimensions" in brief
    assert brief["tools"][0]["id"] == "list_customers"
    assert brief["transcripts"][0]["seed_id"] == "seed-1"
    assert "submit_shape" in brief


def test_request_llm_judgment_no_transcripts(mcp: FastMCP, session: ElliotSession) -> None:
    session.connector = _connector()
    result = _tool(mcp, "elliot_request_llm_judgment")()
    assert "text" in result or "error" in result


def test_submit_llm_judgment_combines_and_saves(mcp: FastMCP, session: ElliotSession) -> None:
    session.connector = _connector()
    _tool(mcp, "elliot_submit_audit_transcript")(_transcript())
    judgment = json.dumps(
        {
            "model": "claude-test",
            "ratings": [{"dimension": "description_clarity", "score": 9, "rationale": "clear"}],
            "findings": [],
            "summary": "looks good",
        }
    )
    result = _tool(mcp, "elliot_submit_llm_judgment")(judgment)
    assert result["passed"] is True
    assert result["llm_model"] == "claude-test"
    assert result["dimension_sources"]["description_clarity"] == "llm"
    assert Path(result["report_path"]).exists()


def test_submit_llm_judgment_error_finding_fails(mcp: FastMCP, session: ElliotSession) -> None:
    session.connector = _connector()
    _tool(mcp, "elliot_submit_audit_transcript")(_transcript())
    judgment = json.dumps(
        {
            "model": "claude-test",
            "findings": [
                {
                    "tool_id": "list_customers",
                    "severity": "error",
                    "message": "vague",
                    "suggestion": "fix",
                }
            ],
        }
    )
    result = _tool(mcp, "elliot_submit_llm_judgment")(judgment)
    assert result["passed"] is False


def test_submit_llm_judgment_invalid_json(mcp: FastMCP, session: ElliotSession) -> None:
    session.connector = _connector()
    _tool(mcp, "elliot_submit_audit_transcript")(_transcript())
    result = _tool(mcp, "elliot_submit_llm_judgment")("{bad")
    assert "text" in result or "error" in result


def test_submit_llm_judgment_no_connector(mcp: FastMCP) -> None:
    result = _tool(mcp, "elliot_submit_llm_judgment")("{}")
    assert "text" in result or "error" in result


def test_audit_results_dir_defaults_under_workspace(tmp_path: Path, monkeypatch):
    """B1/H9: results must land under the session workspace (ELLIOT_WORKSPACE),
    not a cwd-relative '.elliot' that is read-only on the hosted builder."""
    monkeypatch.delenv("ELLIOT_AUDIT_RESULTS_DIR", raising=False)
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.audit_tools._AUDIT_RESULTS_DIR_ENV", None, raising=False
    )
    from elliot_mcp_plugin.tools.audit_tools import _audit_results_dir

    session = ElliotSession(cwd=str(tmp_path))
    expected = session.workspace._dir / "audit-results"
    assert _audit_results_dir(session) == expected
    # And the resolved path lives under the workspace, not the process cwd.
    assert str(expected).startswith(str(tmp_path))


def test_submit_stamps_current_build_id(mcp: FastMCP, session: ElliotSession) -> None:
    session.build_id = "build-abc123"
    _tool(mcp, "elliot_submit_audit_transcript")(_transcript())
    assert session.audit_transcripts[0].build_id == "build-abc123"


def test_judge_scopes_to_current_build(mcp: FastMCP, session: ElliotSession) -> None:
    from elliot_core.audit.models import AuditTranscript

    session.connector = _connector()
    session.build_id = "build-new"
    # A stale transcript from a previous build must not count by default.
    session.audit_transcripts.append(
        AuditTranscript(seed_id="stale", task="old", build_id="build-old")
    )
    _tool(mcp, "elliot_submit_audit_transcript")(_transcript("fresh"))

    current = _tool(mcp, "elliot_judge_audit")()  # default scope="current"
    assert current["transcript_count"] == 1

    every = _tool(mcp, "elliot_judge_audit")(scope="all")
    assert every["transcript_count"] == 2


def test_judge_errors_when_only_stale_transcripts(mcp: FastMCP, session: ElliotSession) -> None:
    from elliot_core.audit.models import AuditTranscript

    session.connector = _connector()
    session.build_id = "build-new"
    session.audit_transcripts.append(
        AuditTranscript(seed_id="stale", task="old", build_id="build-old")
    )
    res = _tool(mcp, "elliot_judge_audit")()
    assert "NO_CURRENT_BUILD_TRANSCRIPTS" in res.get("text", "")
