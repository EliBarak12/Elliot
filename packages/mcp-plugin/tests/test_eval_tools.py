"""Tests for eval and quality MCP tools."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.eval_tools import register_eval_tools


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    server = FastMCP("test")
    register_eval_tools(server, session)
    return server


def _tool(mcp: FastMCP, name: str):
    fn = mcp._tool_manager._tools[name].fn
    if inspect.iscoroutinefunction(fn):
        try:
            asyncio.get_running_loop()
            return fn
        except RuntimeError:

            def sync_wrapper(*args, **kwargs):
                return asyncio.run(fn(*args, **kwargs))

            return sync_wrapper
    return fn


async def _load_table_and_build_connector(session: ElliotSession, tmp_path: Path) -> None:
    """Load a CSV, create a tool, and build a connector on the session."""
    from elliot_mcp_plugin.tools.connector_tools import register_connector_tools
    from elliot_mcp_plugin.tools.source_tools import register_source_tools
    from elliot_mcp_plugin.tools.tool_tools import register_tool_tools

    s = FastMCP("src")
    register_source_tools(s, session)
    p = tmp_path / "items.csv"
    p.write_text("id,val\n1,alpha\n2,beta\n")
    await s._tool_manager._tools["elliot_discover_source"].fn(
        source_type="file", config={"path": str(p)}, name="items"
    )

    t = FastMCP("tt")
    register_tool_tools(t, session)
    t._tool_manager._tools["elliot_create_tool"].fn(
        name="list_items",
        description="Returns all items from the items table",
        category="READ",
        sql='SELECT * FROM "items"',
        parameters=[],
    )

    c = FastMCP("ct")
    register_connector_tools(c, session)
    c._tool_manager._tools["elliot_build_connector"].fn(name="Test", slug="test", version="1.0.0")


def _write_eval_suite(tmp_path: Path, suite: dict, suite_id: str) -> Path:  # type: ignore[type-arg]
    eval_dir = tmp_path / ".elliot" / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    p = eval_dir / f"{suite_id}.json"
    p.write_text(json.dumps(suite))
    return p


# ---------------------------------------------------------------------------
# elliot_run_eval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_eval_no_connector(mcp: FastMCP, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.eval_tools.EVAL_DIR", str(tmp_path / ".elliot" / "eval")
    )
    suite = {
        "id": "s1",
        "name": "Suite 1",
        "cases": [],
    }
    _write_eval_suite(tmp_path, suite, "s1")

    result = await _tool(mcp, "elliot_run_eval")(suite_id="s1")
    assert "text" in result or "error" in result


@pytest.mark.asyncio
async def test_run_eval_suite_not_found(mcp: FastMCP, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.eval_tools.EVAL_DIR", str(tmp_path / ".elliot" / "eval")
    )
    result = await _tool(mcp, "elliot_run_eval")(suite_id="nonexistent")
    assert "text" in result or "error" in result


@pytest.mark.asyncio
async def test_run_eval_empty_suite(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.eval_tools.EVAL_DIR",
        str(tmp_path / ".elliot" / "eval"),
    )
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.eval_tools.EVAL_RESULTS_DIR",
        str(tmp_path / ".elliot" / "eval-results"),
    )
    await _load_table_and_build_connector(session, tmp_path)

    suite = {"id": "empty_suite", "name": "Empty", "cases": []}
    _write_eval_suite(tmp_path, suite, "empty_suite")

    result = await _tool(mcp, "elliot_run_eval")(suite_id="empty_suite")
    assert "suite_id" in result
    assert result["suite_id"] == "empty_suite"
    assert result["passed"] == 0
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_run_eval_with_cases(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.eval_tools.EVAL_DIR",
        str(tmp_path / ".elliot" / "eval"),
    )
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.eval_tools.EVAL_RESULTS_DIR",
        str(tmp_path / ".elliot" / "eval-results"),
    )
    await _load_table_and_build_connector(session, tmp_path)

    suite = {
        "id": "data_suite",
        "name": "Data Suite",
        "cases": [
            {
                "id": "case1",
                "tool_id": "list_items",
                "params": {},
                "match_mode": "shape",
                "description": "List returns rows",
            }
        ],
    }
    _write_eval_suite(tmp_path, suite, "data_suite")

    result = await _tool(mcp, "elliot_run_eval")(suite_id="data_suite")
    assert "suite_id" in result
    assert isinstance(result["score"], float)


# ---------------------------------------------------------------------------
# elliot_quality_scan
# ---------------------------------------------------------------------------


def test_quality_scan_no_connector(mcp: FastMCP):
    result = _tool(mcp, "elliot_quality_scan")()
    assert "text" in result or "error" in result


def test_quality_scan_with_connector(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.eval_tools.EVAL_RESULTS_DIR",
        str(tmp_path / ".elliot" / "eval-results"),
    )
    asyncio.run(_load_table_and_build_connector(session, tmp_path))

    result = _tool(mcp, "elliot_quality_scan")()
    assert "overall_score" in result
    assert "tool_scores" in result
    assert isinstance(result["tool_scores"], list)
    assert result["error_count"] >= 0


def test_quality_scan_with_previous_eval(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path, monkeypatch
):
    results_dir = tmp_path / ".elliot" / "eval-results"
    results_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.eval_tools.EVAL_RESULTS_DIR",
        str(results_dir),
    )
    import datetime

    from elliot_core.eval.models import EvalRunResult
    from elliot_core.eval.runner import save_result

    prev = EvalRunResult(
        suite_id="prev",
        run_at=datetime.datetime.now(datetime.UTC).isoformat(),
        score=0.8,
        passed=4,
        failed=1,
    )
    save_result(prev, results_dir)

    asyncio.run(_load_table_and_build_connector(session, tmp_path))

    result = _tool(mcp, "elliot_quality_scan")()
    assert "last_eval_score" in result
    assert result["last_eval_score"] == pytest.approx(0.8, abs=0.01)


# ---------------------------------------------------------------------------
# elliot_run_eval — inline cases (the Cloud path: no file, no shared dir)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_eval_inline_cases_pass(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.eval_tools.EVAL_RESULTS_DIR",
        str(tmp_path / ".elliot" / "eval-results"),
    )
    await _load_table_and_build_connector(session, tmp_path)

    result = await _tool(mcp, "elliot_run_eval")(
        cases=[
            {
                "id": "c1",
                "tool_id": "list_items",
                "arguments": {},
                "expect": {"no_error": True, "min_rows": 1, "fields_present": ["id"]},
            }
        ]
    )
    assert result["format"] == "inline"
    assert result["passed"] == 1
    assert result["failed"] == 0
    assert result["score"] == 100.0


@pytest.mark.asyncio
async def test_run_eval_inline_unknown_tool_fails_gracefully(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    await _load_table_and_build_connector(session, tmp_path)
    result = await _tool(mcp, "elliot_run_eval")(
        cases=[{"id": "c1", "tool_id": "does_not_exist", "arguments": {}}]
    )
    assert result["format"] == "inline"
    assert result["passed"] == 0
    assert result["failed"] == 1


@pytest.mark.asyncio
async def test_run_eval_inline_empty_cases_errors(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    await _load_table_and_build_connector(session, tmp_path)
    result = await _tool(mcp, "elliot_run_eval")(cases=[])
    assert "text" in result or "error" in result
