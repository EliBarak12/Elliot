"""Tests for Studio MCP tools: session_summary, connector_info, audit_log, metrics, run_sql."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.studio_tools import register_studio_tools


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    server = FastMCP("test")
    register_studio_tools(server, session)
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


def _load_table(session: ElliotSession, tmp_path: Path) -> None:
    from elliot_mcp_plugin.tools.source_tools import register_source_tools

    s = FastMCP("src")
    register_source_tools(s, session)
    p = tmp_path / "items.csv"
    p.write_text("id,val\n1,alpha\n2,beta\n")
    _tool(s, "elliot_discover_source")(source_type="file", config={"path": str(p)}, name="items")


def _write_audit(tmp_path: Path, entries: list[dict]) -> Path:  # type: ignore[type-arg]
    audit_path = tmp_path / ".elliot" / "audit.ndjson"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )
    return audit_path


# ---------------------------------------------------------------------------
# elliot_session_summary
# ---------------------------------------------------------------------------


def test_session_summary_empty(mcp: FastMCP):
    result = _tool(mcp, "elliot_session_summary")()
    assert result["sources"] == 0
    assert result["tools"] == 0
    assert result["skills"] == 0
    assert result["product_context"] is None


def test_session_summary_with_data(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    from elliot_mcp_plugin.tools.tool_tools import register_tool_tools

    t = FastMCP("tt")
    register_tool_tools(t, session)
    _load_table(session, tmp_path)
    t._tool_manager._tools["elliot_create_tool"].fn(
        name="list_items",
        description="Returns all items from the items table",
        category="READ",
        sql='SELECT * FROM "items"',
        parameters=[],
    )
    result = _tool(mcp, "elliot_session_summary")()
    assert result["sources"] == 1
    assert result["tools"] == 1


# ---------------------------------------------------------------------------
# studio_get_connector_info
# ---------------------------------------------------------------------------


def test_connector_info_no_connector(mcp: FastMCP):
    result = _tool(mcp, "studio_get_connector_info")()
    assert result["connector_built"] is False
    assert "connector" not in result


def test_connector_info_with_connector(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    from elliot_mcp_plugin.tools.connector_tools import register_connector_tools
    from elliot_mcp_plugin.tools.tool_tools import register_tool_tools

    ct = FastMCP("ct")
    register_connector_tools(ct, session)
    tt = FastMCP("tt")
    register_tool_tools(tt, session)

    _load_table(session, tmp_path)
    tt._tool_manager._tools["elliot_create_tool"].fn(
        name="list_items",
        description="Returns all items from the items table",
        category="READ",
        sql='SELECT * FROM "items"',
        parameters=[],
    )
    ct._tool_manager._tools["elliot_build_connector"].fn(name="Test", slug="test", version="1.0.0")

    result = _tool(mcp, "studio_get_connector_info")()
    assert result["connector_built"] is True
    assert "connector" in result
    assert result["tool_count"] == 1


# ---------------------------------------------------------------------------
# studio_get_audit_log
# ---------------------------------------------------------------------------


def test_audit_log_no_file(mcp: FastMCP, session: ElliotSession, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.studio_tools.AUDIT_PATH",
        str(tmp_path / "nonexistent.ndjson"),
    )
    result = _tool(mcp, "studio_get_audit_log")(limit=10)
    assert result == []


def test_audit_log_returns_entries(mcp: FastMCP, tmp_path: Path, monkeypatch):
    entries = [{"tool_id": "t1", "ts": 1}, {"tool_id": "t2", "ts": 2}]
    audit_path = _write_audit(tmp_path, entries)
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.studio_tools.AUDIT_PATH",
        str(audit_path),
    )
    result = _tool(mcp, "studio_get_audit_log")(limit=10)
    assert len(result) == 2
    assert result[0]["tool_id"] == "t1"


def test_audit_log_respects_limit(mcp: FastMCP, tmp_path: Path, monkeypatch):
    entries = [{"tool_id": f"t{i}", "ts": i} for i in range(20)]
    audit_path = _write_audit(tmp_path, entries)
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.studio_tools.AUDIT_PATH",
        str(audit_path),
    )
    result = _tool(mcp, "studio_get_audit_log")(limit=5)
    assert len(result) == 5
    assert result[-1]["tool_id"] == "t19"


# ---------------------------------------------------------------------------
# studio_get_metrics
# ---------------------------------------------------------------------------


def test_metrics_no_file(mcp: FastMCP, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.studio_tools.AUDIT_PATH",
        str(tmp_path / "nonexistent.ndjson"),
    )
    result = _tool(mcp, "studio_get_metrics")(days=30)
    assert result["metrics"] == []


def test_metrics_aggregates_correctly(mcp: FastMCP, tmp_path: Path, monkeypatch):
    now = time.time()
    entries = [
        {"tool_id": "list_items", "ts": now, "error": False, "duration_ms": 100},
        {"tool_id": "list_items", "ts": now, "error": True, "duration_ms": 200},
        {"tool_id": "count_items", "ts": now, "error": False, "duration_ms": 50},
    ]
    audit_path = _write_audit(tmp_path, entries)
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.studio_tools.AUDIT_PATH",
        str(audit_path),
    )
    result = _tool(mcp, "studio_get_metrics")(days=30)
    metrics = {m["tool_id"]: m for m in result["metrics"]}
    assert metrics["list_items"]["call_count"] == 2
    assert metrics["list_items"]["error_rate"] == 0.5
    assert metrics["list_items"]["avg_duration_ms"] == 150.0
    assert metrics["count_items"]["call_count"] == 1
    assert result["days"] == 30


def test_metrics_filters_old_entries(mcp: FastMCP, tmp_path: Path, monkeypatch):
    old_ts = time.time() - 100 * 86400  # 100 days ago
    now = time.time()
    entries = [
        {"tool_id": "old_tool", "ts": old_ts, "error": False, "duration_ms": 10},
        {"tool_id": "new_tool", "ts": now, "error": False, "duration_ms": 20},
    ]
    audit_path = _write_audit(tmp_path, entries)
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.studio_tools.AUDIT_PATH",
        str(audit_path),
    )
    result = _tool(mcp, "studio_get_metrics")(days=30)
    tool_ids = [m["tool_id"] for m in result["metrics"]]
    assert "new_tool" in tool_ids
    assert "old_tool" not in tool_ids


def test_metrics_skips_invalid_json_lines(mcp: FastMCP, tmp_path: Path, monkeypatch):
    audit_path = tmp_path / ".elliot" / "audit.ndjson"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    audit_path.write_text(
        f"{{not valid json}}\n{json.dumps({'tool_id': 'good', 'ts': now, 'error': False, 'duration_ms': 5})}\n"
    )
    monkeypatch.setattr(
        "elliot_mcp_plugin.tools.studio_tools.AUDIT_PATH",
        str(audit_path),
    )
    result = _tool(mcp, "studio_get_metrics")(days=30)
    assert len(result["metrics"]) == 1


# ---------------------------------------------------------------------------
# studio_run_sql
# ---------------------------------------------------------------------------


def test_run_sql_select(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_table(session, tmp_path)
    result = _tool(mcp, "studio_run_sql")(sql='SELECT * FROM "items"')
    assert result["row_count"] == 2
    assert len(result["rows"]) == 2


def test_run_sql_rejects_non_select(mcp: FastMCP):
    result = _tool(mcp, "studio_run_sql")(sql="DROP TABLE items")
    assert "text" in result or "error" in result


def test_run_sql_invalid_sql(mcp: FastMCP):
    result = _tool(mcp, "studio_run_sql")(sql="SELECT * FROM nonexistent_table_xyz")
    assert "text" in result or "error" in result
