"""Tests for skill, context, and connector MCP tools."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.connector_tools import register_connector_tools
from elliot_mcp_plugin.tools.context_tools import register_context_tools
from elliot_mcp_plugin.tools.skill_tools import register_skill_tools
from elliot_mcp_plugin.tools.tool_tools import register_tool_tools


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


@pytest.fixture()
def mcp(session: ElliotSession) -> FastMCP:
    server = FastMCP("test")
    register_skill_tools(server, session)
    register_context_tools(server, session)
    register_connector_tools(server, session)
    register_tool_tools(server, session)
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


def _load_and_create_tool(mcp: FastMCP, session: ElliotSession, tmp_path: Path) -> str:
    from elliot_mcp_plugin.tools.source_tools import register_source_tools

    s = FastMCP("src")
    register_source_tools(s, session)
    p = tmp_path / "items.csv"
    p.write_text("id,val\n1,a\n2,b\n")
    _tool(s, "elliot_discover_source")(source_type="file", config={"path": str(p)}, name="items")
    r = _tool(mcp, "elliot_create_tool")(
        name="count_items",
        description="Returns the count of all items in stock",
        category="READ",
        sql='SELECT COUNT(*) as cnt FROM "items"',
        parameters=[],
    )
    return r["tool_id"]


# ---------------------------------------------------------------------------
# skill tools
# ---------------------------------------------------------------------------


def test_list_skills_empty(mcp: FastMCP):
    result = _tool(mcp, "elliot_list_skills")()
    assert result["count"] == 0


def test_create_skill_unknown_tool_returns_error(mcp: FastMCP):
    result = _tool(mcp, "elliot_create_skill")(
        name="my_skill",
        description="Does something useful",
        steps=[{"alias": "step1", "tool_id": "nonexistent_tool", "params": {}}],
        input_parameters=[],
    )
    assert "text" in result or "error" in result


def test_create_skill_registers(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_and_create_tool(mcp, session, tmp_path)
    result = _tool(mcp, "elliot_create_skill")(
        name="item_count_skill",
        description="Counts all items in a single step",
        steps=[{"alias": "count", "tool_id": "count_items", "params": {}}],
        input_parameters=[],
    )
    assert result["status"] == "created"
    skill_id = result["skill_id"]
    assert session.registry.get_skill(skill_id) is not None


def test_create_prose_skill_without_steps(mcp: FastMCP, session: ElliotSession):
    """A prose-only skill needs no steps — just instructions."""
    result = _tool(mcp, "elliot_create_skill")(
        name="onboarding_flow",
        description="Walks the agent through onboarding a new customer",
        instructions="1. Create the account.\n2. If trial, set the flag, else bill them.",
        when_to_use="When a new customer signs up.",
    )
    assert result["status"] == "created"
    skill = session.registry.get_skill(result["skill_id"])
    assert skill is not None
    assert skill.steps == []
    assert skill.when_to_use == "When a new customer signs up."
    assert skill.instructions.startswith("1.")


def test_create_skill_with_neither_steps_nor_instructions_errors(mcp: FastMCP):
    result = _tool(mcp, "elliot_create_skill")(
        name="empty_skill",
        description="Does nothing",
    )
    assert "text" in result or "error" in result


def test_preview_prose_skill_returns_guidance(mcp: FastMCP, session: ElliotSession):
    created = _tool(mcp, "elliot_create_skill")(
        name="prose_only",
        description="Prose guidance only",
        instructions="Do the thing, then the other thing.",
        when_to_use="When asked.",
    )
    result = _tool(mcp, "elliot_preview_skill")(skill_id=created["skill_id"])
    assert result["meta"]["kind"] == "prose"
    assert result["meta"]["instructions"] == "Do the thing, then the other thing."
    assert result["rows"] == []


def test_list_skills_after_create(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_and_create_tool(mcp, session, tmp_path)
    _tool(mcp, "elliot_create_skill")(
        name="list_skill",
        description="Lists items using one step only",
        steps=[{"alias": "s1", "tool_id": "count_items", "params": {}}],
        input_parameters=[],
    )
    result = _tool(mcp, "elliot_list_skills")()
    assert result["count"] == 1


def test_get_skill_returns_definition(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_and_create_tool(mcp, session, tmp_path)
    created = _tool(mcp, "elliot_create_skill")(
        name="get_skill",
        description="A skill to get item counts quickly",
        steps=[{"alias": "s1", "tool_id": "count_items", "params": {}}],
        input_parameters=[],
    )
    result = _tool(mcp, "elliot_get_skill")(skill_id=created["skill_id"])
    assert result["name"] == "get_skill"


def test_get_skill_not_found(mcp: FastMCP):
    result = _tool(mcp, "elliot_get_skill")(skill_id="ghost")
    assert "text" in result or "error" in result


def test_delete_skill(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_and_create_tool(mcp, session, tmp_path)
    created = _tool(mcp, "elliot_create_skill")(
        name="del_skill",
        description="A skill to be deleted from registry",
        steps=[{"alias": "s1", "tool_id": "count_items", "params": {}}],
        input_parameters=[],
    )
    sid = created["skill_id"]
    result = _tool(mcp, "elliot_delete_skill")(skill_id=sid)
    assert result["status"] == "deleted"
    assert session.registry.get_skill(sid) is None


def test_delete_skill_not_found(mcp: FastMCP):
    result = _tool(mcp, "elliot_delete_skill")(skill_id="ghost")
    assert "text" in result or "error" in result


# ---------------------------------------------------------------------------
# context tools
# ---------------------------------------------------------------------------


def test_set_context_stores_product_context(mcp: FastMCP, session: ElliotSession):
    result = _tool(mcp, "elliot_set_context")(name="Acme", description="Acme Corp API")
    assert result["status"] == "ok"
    assert session.product_context is not None
    assert session.product_context.name == "Acme"


def test_get_context_returns_none_when_unset(mcp: FastMCP):
    result = _tool(mcp, "elliot_get_context")()
    assert result["context"] is None


def test_get_context_after_set(mcp: FastMCP, session: ElliotSession):
    _tool(mcp, "elliot_set_context")(name="TestCo", base_url="https://api.testco.com")
    result = _tool(mcp, "elliot_get_context")()
    assert result["context"]["name"] == "TestCo"


def test_get_session_state_empty(mcp: FastMCP):
    result = _tool(mcp, "elliot_get_session_state")()
    assert result["source_count"] == 0
    assert result["tool_count"] == 0
    assert result["skill_count"] == 0
    assert result["connector_built"] is False


def test_get_session_state_reflects_loaded_data(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    _load_and_create_tool(mcp, session, tmp_path)
    result = _tool(mcp, "elliot_get_session_state")()
    assert result["source_count"] == 1
    assert result["tool_count"] == 1


# ---------------------------------------------------------------------------
# connector tools
# ---------------------------------------------------------------------------


def test_build_connector_returns_built_status(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_and_create_tool(mcp, session, tmp_path)
    result = _tool(mcp, "elliot_build_connector")(
        name="TestConnector", slug="test", version="1.0.0"
    )
    assert result["status"] == "built"
    assert session.connector is not None


def test_build_connector_unknown_tool_id_errors(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    # A typo'd / nonexistent tool_id must fail loudly, not silently build an
    # empty connector that reports "built" with tool_count 0.
    _load_and_create_tool(mcp, session, tmp_path)
    result = _tool(mcp, "elliot_build_connector")(
        name="TestConnector",
        slug="test",
        version="1.0.0",
        tool_ids=["count_items", "does_not_exist"],
    )
    assert result.get("status") != "built"
    blob = result.get("text", "") + str(result)
    assert "VALIDATION_UNKNOWN_TOOL" in blob
    assert "does_not_exist" in blob
    # The valid tool alone still builds fine.
    ok = _tool(mcp, "elliot_build_connector")(
        name="TestConnector", slug="test", version="1.0.0", tool_ids=["count_items"]
    )
    assert ok["status"] == "built"
    assert ok["tool_count"] == 1


def test_build_connector_unknown_skill_id_errors(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    _load_and_create_tool(mcp, session, tmp_path)
    result = _tool(mcp, "elliot_build_connector")(
        name="TestConnector", slug="test", version="1.0.0", skill_ids=["no_such_skill"]
    )
    assert result.get("status") != "built"
    assert "VALIDATION_UNKNOWN_SKILL" in (result.get("text", "") + str(result))


def test_export_connector_writes_file(mcp: FastMCP, session: ElliotSession, tmp_path: Path):
    _load_and_create_tool(mcp, session, tmp_path)
    _tool(mcp, "elliot_build_connector")(name="MyConnector", slug="my", version="1.0.0")
    export_path = str(tmp_path / "connector.json")
    result = _tool(mcp, "elliot_export_connector")(path=export_path)
    assert result["status"] == "exported"
    assert Path(export_path).exists()
    data = json.loads(Path(export_path).read_text())
    assert data["name"] == "MyConnector"


def test_export_connector_without_build_returns_error(mcp: FastMCP):
    result = _tool(mcp, "elliot_export_connector")(path="/tmp/test.json")
    assert "text" in result or "error" in result


def test_get_connection_config(mcp: FastMCP):
    result = _tool(mcp, "elliot_get_connection_config")()
    assert result["type"] == "http"
    assert "localhost:3001" in result["url"]
    # Trailing slash matters: strict MCP clients drop POST bodies on 307s.
    assert result["url"].endswith("/mcp/")


def test_stop_runtime_when_not_running(mcp: FastMCP):
    result = _tool(mcp, "elliot_stop_runtime")()
    assert result["status"] == "not_running"


# ── elliot_start_runtime: truthful health-check + log capture ────────────────


def test_start_runtime_refuses_when_no_connector(
    mcp: FastMCP, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: start_runtime used to return success even when the
    runtime couldn't load a connector. Now it must fail loudly with a
    RUNTIME_NO_CONNECTOR code if no connector path exists."""
    # monkeypatch.chdir restores cwd automatically; the previous try/finally
    # raw os.chdir would leak cwd into other tests if anything in the body
    # raised before the finally clause ran.
    monkeypatch.chdir(tmp_path)
    result = _tool(mcp, "elliot_start_runtime")()
    assert "text" in result
    assert "RUNTIME_NO_CONNECTOR" in result["text"]


def test_start_runtime_reports_failure_when_process_dies(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: a runtime subprocess that exits immediately used to
    return `status: running`. It must now return RUNTIME_START_FAILED with
    a tail of the captured log."""
    import subprocess

    connector_path = tmp_path / "connector.json"
    connector_path.write_text("{}", encoding="utf-8")

    class _FakeProc:
        def __init__(self) -> None:
            self.pid = 4242
            self._polled = 0

        def poll(self) -> int | None:
            # Report alive on first poll (so the entry guard passes), then
            # report exit code 1 to simulate an immediate crash.
            self._polled += 1
            return None if self._polled <= 1 else 1

        def terminate(self) -> None:
            pass

        def wait(self, timeout: float = 0) -> int:
            return 1

    def _fake_popen(*args: object, **kwargs: object) -> _FakeProc:
        import contextlib

        # Write a fake stderr line to the runtime log path the tool opens.
        stdout = kwargs.get("stdout")
        if hasattr(stdout, "write"):
            with contextlib.suppress(Exception):
                stdout.write(b"ImportError: boom from fake runtime\n")
        return _FakeProc()

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = _tool(mcp, "elliot_start_runtime")(port=3099, connector_path=str(connector_path))
    assert "text" in result
    assert "RUNTIME_START_FAILED" in result["text"]
    # The log path should now exist and elliot_runtime_logs should return it.
    logs = _tool(mcp, "elliot_runtime_logs")()
    assert logs["exists"] is True
    assert "boom from fake runtime" in logs["tail"]


def test_runtime_logs_when_never_started(mcp: FastMCP):
    result = _tool(mcp, "elliot_runtime_logs")()
    assert result["exists"] is False
    assert "tail" in result


# ── elliot_create_skill accepts the loose shapes agents produce ──────────────


def test_create_skill_accepts_arguments_alias_for_params(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    """Regression: agents naturally write `arguments` instead of `params`.
    The tool used to surface a raw pydantic ValidationError; it must now
    transparently accept the alias."""
    _load_and_create_tool(mcp, session, tmp_path)
    result = _tool(mcp, "elliot_create_skill")(
        name="alias_skill",
        description="Uses arguments alias instead of params",
        steps=[{"alias": "count", "tool_id": "count_items", "arguments": {"x": 1}}],
        input_parameters=[],
    )
    assert result.get("status") == "created"
    skill = session.registry.get_skill(result["skill_id"])
    assert skill is not None
    assert skill.steps[0].params == {"x": 1}


def test_create_skill_missing_alias_gives_clear_error(
    mcp: FastMCP, session: ElliotSession, tmp_path: Path
):
    _load_and_create_tool(mcp, session, tmp_path)
    result = _tool(mcp, "elliot_create_skill")(
        name="bad_skill",
        description="Skill with a step missing alias",
        steps=[{"tool_id": "count_items", "params": {}}],
        input_parameters=[],
    )
    # The error must mention the missing field explicitly.
    payload = result.get("text") or result.get("error") or ""
    assert "alias" in payload
    assert "INVALID_SKILL" in payload
