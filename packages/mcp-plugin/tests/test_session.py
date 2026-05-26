"""Tests for ElliotSession: save/load state roundtrip."""

from __future__ import annotations

from pathlib import Path

import pytest

from elliot_core.types.connector import ProductContext
from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import ToolDefinition
from elliot_mcp_plugin.session import ElliotSession


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


def test_load_empty_session_is_noop(session: ElliotSession):
    session.load()
    assert session.product_context is None
    assert session.sources == {}


def test_save_and_load_product_context(session: ElliotSession, tmp_path: Path):
    session.product_context = ProductContext(
        name="Acme API", description="Acme's REST API", base_url="https://acme.com"
    )
    session.save()

    restored = ElliotSession(cwd=str(tmp_path))
    restored.load()
    assert restored.product_context is not None
    assert restored.product_context.name == "Acme API"
    assert restored.product_context.base_url == "https://acme.com"


def test_save_and_load_sources(session: ElliotSession, tmp_path: Path):
    src = SourceConfig(id="api", name="API", type="rest", url="https://acme.com/v1")
    session.sources["api"] = src
    session.save()

    restored = ElliotSession(cwd=str(tmp_path))
    restored.load()
    assert "api" in restored.sources
    assert restored.sources["api"].url == "https://acme.com/v1"


def test_save_and_load_tools(session: ElliotSession, tmp_path: Path):
    tool = ToolDefinition(
        id="list_items",
        name="List items",
        description="Return items",
        category="READ",
        source_ids=["api"],
    )
    src = SourceConfig(id="api", name="API", type="rest", url="https://acme.com/v1")
    session.sources["api"] = src
    session.registry.add(tool)
    session.save()

    restored = ElliotSession(cwd=str(tmp_path))
    restored.load()
    assert "api" in restored.sources
    assert len(restored.registry.get_all()) == 1
    assert restored.registry.get_all()[0].id == "list_items"


def test_save_with_no_context(session: ElliotSession, tmp_path: Path):
    session.save()
    restored = ElliotSession(cwd=str(tmp_path))
    restored.load()
    assert restored.product_context is None


def test_save_and_load_tool_sql(session: ElliotSession, tmp_path: Path):
    session.tool_sql["list_orders"] = 'SELECT * FROM "orders" LIMIT 50'
    session.tool_sql["total_revenue"] = 'SELECT SUM(amount) AS total FROM "orders"'
    session.save()

    restored = ElliotSession(cwd=str(tmp_path))
    restored.load()
    assert restored.tool_sql["list_orders"] == 'SELECT * FROM "orders" LIMIT 50'
    assert restored.tool_sql["total_revenue"] == 'SELECT SUM(amount) AS total FROM "orders"'


def test_save_and_load_skills(session: ElliotSession, tmp_path: Path):
    from elliot_core.types.tool import SkillDefinition, SkillStep

    skill = SkillDefinition(
        id="my_skill",
        name="My skill",
        description="A skill",
        steps=[SkillStep(alias="step1", tool_id="list_items", params={})],
    )
    session.registry.add_skill(skill)
    session.save()

    restored = ElliotSession(cwd=str(tmp_path))
    restored.load()
    assert restored.registry.get_skill("my_skill") is not None


def test_load_session_without_tool_sql_key(session: ElliotSession, tmp_path: Path):
    # Older sessions saved before tool_sql was added should load without error
    session.save()
    data_path = tmp_path / ".elliot" / "session.json"
    import json

    data = json.loads(data_path.read_text())
    del data["tool_sql"]
    data_path.write_text(json.dumps(data))

    restored = ElliotSession(cwd=str(tmp_path))
    restored.load()
    assert restored.tool_sql == {}


def test_refresh_from_disk_picks_up_external_writes(tmp_path: Path):
    """Regression: when the agent's MCP client spawns a separate plugin
    process that writes to the shared workspace, the Studio's plugin
    process must be able to see the new tools/sources without a restart.
    refresh_from_disk() reloads session.json when its mtime advances."""
    import os
    import time

    # Plugin "A" — what the Studio is connected to.
    studio_session = ElliotSession(cwd=str(tmp_path))
    studio_session.load()
    assert studio_session.registry.get_all() == []

    # Plugin "B" — pretend the agent's client spawned its own plugin and
    # created a tool. It writes to the same workspace.
    agent_session = ElliotSession(cwd=str(tmp_path))
    agent_session.load()
    tool = ToolDefinition(
        id="agent_tool",
        name="Agent Tool",
        description="Created by the agent",
        category="READ",
        source_ids=[],
    )
    agent_session.registry.add(tool)
    agent_session.save()

    # Bump mtime past Studio's tracked mtime — filesystems can have 1s
    # resolution, so an explicit os.utime is more reliable than time.sleep.
    session_path = tmp_path / ".elliot" / "session.json"
    future = time.time() + 1
    os.utime(session_path, (future, future))

    # Studio's plugin polls and refreshes — should now see the agent's tool.
    reloaded = studio_session.refresh_from_disk()
    assert reloaded is True
    names = [t.id for t in studio_session.registry.get_all()]
    assert "agent_tool" in names


def test_refresh_from_disk_is_noop_when_unchanged(session: ElliotSession):
    """Calling refresh repeatedly without any external write must not
    re-read or mutate state — it's invoked on every list endpoint and
    needs to be effectively free in the steady state."""
    session.save()
    assert session.refresh_from_disk() is False
    assert session.refresh_from_disk() is False


def test_discard_connector_clears_state_and_file(session: ElliotSession):
    from elliot_core.types.connector import ConnectorConfig

    session.connector = ConnectorConfig(
        name="acme",
        slug="acme",
        version="0.1.0",
        sources=[],
        tools=[],
    )
    path = session.workspace._dir / "connector.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"name": "acme"}', encoding="utf-8")

    result = session.discard_connector()
    assert result == {"status": "discarded", "had_connector": True, "removed_file": True}
    assert session.connector is None
    assert not path.exists()


def test_discard_connector_when_nothing_built_is_noop(session: ElliotSession):
    result = session.discard_connector()
    assert result == {"status": "discarded", "had_connector": False, "removed_file": False}
    assert session.connector is None


def test_save_then_refresh_does_not_re_read(session: ElliotSession):
    """Our own save() must update the tracked mtime so the very next
    list call doesn't pointlessly clear-and-reload what we just wrote."""
    tool = ToolDefinition(
        id="local_tool",
        name="Local Tool",
        description="x",
        category="READ",
        source_ids=[],
    )
    session.registry.add(tool)
    session.save()
    # Should be a no-op — we just wrote it.
    assert session.refresh_from_disk() is False
    assert [t.id for t in session.registry.get_all()] == ["local_tool"]
