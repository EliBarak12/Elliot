"""Tests for ConnectorBuilder."""

from __future__ import annotations

import pytest

from elliot_core.connector.builder import ConnectorBuilder
from elliot_core.errors import ElliotError
from elliot_core.types.connector import ConnectorBranding
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


def test_build_carries_branding():
    branding = ConnectorBranding(accent="#c02434", logo="https://cdn.example/logo.svg")
    config = (
        ConnectorBuilder()
        .set_meta(name="Test", version="1.0.0", slug="test")
        .build(sources=[_source()], tools=[_tool()], branding=branding)
    )
    assert config.branding is not None
    assert config.branding.accent == "#c02434"
    assert config.branding.logo == "https://cdn.example/logo.svg"


def test_build_defaults_to_no_branding():
    config = (
        ConnectorBuilder()
        .set_meta(name="Test", version="1.0.0", slug="test")
        .build(sources=[_source()], tools=[_tool()])
    )
    assert config.branding is None


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


def test_build_carries_instructions():
    config = (
        ConnectorBuilder()
        .set_meta(
            name="Test",
            version="1.0.0",
            slug="test",
            instructions="Always paginate with the cursor parameter.",
        )
        .build(sources=[_source()], tools=[_tool()])
    )
    assert config.instructions == "Always paginate with the cursor parameter."


def test_build_instructions_default_empty():
    config = (
        ConnectorBuilder()
        .set_meta(name="Test", version="1.0.0", slug="test")
        .build(sources=[_source()], tools=[_tool()])
    )
    assert config.instructions == ""


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
