"""Tests for ConnectorBuilder."""

from __future__ import annotations

import pytest

from elliot_core.connector.builder import ConnectorBuilder
from elliot_core.errors import ElliotError
from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import ToolDefinition


def _source() -> SourceConfig:
    return SourceConfig(id="src", name="Source", type="rest", url="https://api.example.com")


def _tool() -> ToolDefinition:
    return ToolDefinition(
        id="list_items",
        name="List items",
        description="Return items",
        category="READ",
        source_ids=["src"],
    )


def test_build_without_set_meta_raises():
    with pytest.raises(ElliotError) as exc_info:
        ConnectorBuilder().build(sources=[_source()], tools=[_tool()])
    assert exc_info.value.code == "INVALID_CONNECTOR"


def test_build_returns_connector_config():
    config = (
        ConnectorBuilder()
        .set_meta(name="Test", version="1.0.0", slug="test", description="A test connector")
        .build(sources=[_source()], tools=[_tool()])
    )
    assert config.name == "Test"
    assert config.slug == "test"
    assert len(config.tools) == 1


def test_build_with_skills():
    from elliot_core.types.tool import SkillDefinition, SkillStep

    skill = SkillDefinition(
        id="my_skill",
        name="My skill",
        description="desc",
        steps=[SkillStep(alias="step1", tool_id="list_items", params={})],
    )
    config = (
        ConnectorBuilder()
        .set_meta(name="Test", version="1.0.0", slug="test")
        .build(sources=[_source()], tools=[_tool()], skills=[skill])
    )
    assert len(config.skills) == 1
    assert config.skills[0].id == "my_skill"
