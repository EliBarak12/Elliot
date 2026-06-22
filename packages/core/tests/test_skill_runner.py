"""Tests for execute_skill and template resolution in skill_runner."""

from __future__ import annotations

from typing import Any

import pytest

from elliot_core.errors import ElliotError
from elliot_core.tools.executor import ToolExecutor
from elliot_core.tools.registry import ToolRegistry
from elliot_core.tools.skill_runner import _lookup, _resolve_value, execute_skill
from elliot_core.types.connector import ConnectorConfig
from elliot_core.types.source import FetchResult, SourceConfig
from elliot_core.types.tool import (
    ParameterDefinition,
    SkillDefinition,
    SkillStep,
    ToolDefinition,
    ToolResult,
)


def _fake_fetch(rows: list[dict[str, Any]]) -> Any:
    async def _fn(source: SourceConfig, secrets: dict[str, str]) -> FetchResult:
        return FetchResult(rows=rows, fetched_at="2024-01-01T00:00:00Z")

    return _fn


def _make_config(tools: list[ToolDefinition]) -> ConnectorConfig:
    return ConnectorConfig(
        name="Test",
        slug="test",
        version="1.0.0",
        sources=[SourceConfig(id="src", name="Src", type="rest", url="https://api.example.com")],
        tools=tools,
    )


def _make_tool(tool_id: str) -> ToolDefinition:
    return ToolDefinition(
        id=tool_id,
        name=tool_id,
        description="desc",
        category="READ",
        source_ids=["src"],
    )


# ── _lookup ───────────────────────────────────────────────────────────────────


def test_lookup_skill_input():
    result = _lookup("skill.input.user_id", {"user_id": "u42"}, {})
    assert result == "u42"


def test_lookup_step_result():
    step_result = ToolResult(rows=[{"name": "Alice"}], meta={})
    result = _lookup("steps.step1.name", {}, {"step1": step_result})
    assert result == "Alice"


def test_lookup_step_no_rows():
    step_result = ToolResult(rows=[], meta={})
    result = _lookup("steps.step1.name", {}, {"step1": step_result})
    assert result is None


def test_lookup_unknown_path():
    result = _lookup("unknown.path", {}, {})
    assert result is None


# ── _resolve_value ────────────────────────────────────────────────────────────


def test_resolve_value_non_string():
    assert _resolve_value(42, {}, {}) == 42


def test_resolve_value_full_template():
    result = _resolve_value("{{ skill.input.x }}", {"x": "hello"}, {})
    assert result == "hello"


def test_resolve_value_inline_template():
    result = _resolve_value("prefix_{{ skill.input.id }}", {"id": "99"}, {})
    assert result == "prefix_99"


def test_resolve_value_full_template_unresolved_returns_none():
    # A full-match template that can't be resolved returns None (not the original string)
    result = _resolve_value("{{ steps.missing.field }}", {}, {})
    assert result is None


# ── execute_skill ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_skill_single_step():
    tool = _make_tool("list_items")
    rows = [{"id": 1}]
    config = _make_config([tool])
    registry = ToolRegistry()
    registry.add(tool)
    executor = ToolExecutor(config, fetch_source=_fake_fetch(rows))

    skill = SkillDefinition(
        id="my_skill",
        name="My Skill",
        description="desc",
        steps=[SkillStep(alias="step1", tool_id="list_items", params={})],
    )
    result = await execute_skill(skill, {}, registry, executor)
    # Strip flattener-injected ``_id`` so the assertion stays focused on
    # the business columns the skill returns.
    assert [{k: v for k, v in r.items() if not k.startswith("_")} for r in result.rows] == rows


@pytest.mark.asyncio
async def test_execute_skill_empty_steps():
    registry = ToolRegistry()
    tool = _make_tool("t1")
    config = _make_config([tool])
    executor = ToolExecutor(config, fetch_source=_fake_fetch([]))

    # A prose-only skill (no steps) still validates because it carries
    # instructions. execute_skill has nothing to run, so it returns an empty
    # result rather than failing.
    skill = SkillDefinition(
        id="empty_skill",
        name="Empty",
        description="desc",
        steps=[],
        instructions="Just guidance, no executable steps.",
    )
    result = await execute_skill(skill, {}, registry, executor)
    assert result.rows == []
    assert result.meta == {}


@pytest.mark.asyncio
async def test_execute_skill_unknown_tool_raises():
    registry = ToolRegistry()
    tool = _make_tool("real_tool")
    config = _make_config([tool])
    executor = ToolExecutor(config, fetch_source=_fake_fetch([]))

    skill = SkillDefinition(
        id="bad_skill",
        name="Bad",
        description="desc",
        steps=[SkillStep(alias="s1", tool_id="ghost_tool", params={})],
    )
    with pytest.raises(ElliotError) as exc_info:
        await execute_skill(skill, {}, registry, executor)
    assert exc_info.value.code == "TOOL_NOT_FOUND"


@pytest.mark.asyncio
async def test_execute_skill_multi_step_binding():
    tool_a = _make_tool("get_user")
    # get_orders must DECLARE the param the skill step binds into it, otherwise
    # the executor now rejects it as an unknown parameter (F-025).
    tool_b = ToolDefinition(
        id="get_orders",
        name="get_orders",
        description="desc",
        category="READ",
        source_ids=["src"],
        parameters=[
            ParameterDefinition(
                name="user_id", type="string", required=False, description="User id filter"
            )
        ],
    )
    rows_a = [{"user_id": "u99", "name": "Alice"}]
    rows_b = [{"order_id": "o1"}]

    fetch_calls: list[str] = []

    async def _fetch(source: SourceConfig, secrets: dict[str, str]) -> FetchResult:
        call_count = len(fetch_calls)
        fetch_calls.append(source.id)
        if call_count == 0:
            return FetchResult(rows=rows_a, fetched_at="2024-01-01T00:00:00Z")
        return FetchResult(rows=rows_b, fetched_at="2024-01-01T00:00:00Z")

    config = _make_config([tool_a, tool_b])
    registry = ToolRegistry()
    registry.add(tool_a)
    registry.add(tool_b)
    executor = ToolExecutor(config, fetch_source=_fetch)

    skill = SkillDefinition(
        id="chain_skill",
        name="Chain",
        description="desc",
        steps=[
            SkillStep(alias="user", tool_id="get_user", params={}),
            SkillStep(
                alias="orders",
                tool_id="get_orders",
                params={"user_id": "{{ steps.user.user_id }}"},
            ),
        ],
    )
    result = await execute_skill(skill, {}, registry, executor)
    assert [{k: v for k, v in r.items() if not k.startswith("_")} for r in result.rows] == rows_b
    # H7: the primary rows are still the final step's, but every step's output
    # is now exposed under meta.steps instead of being silently dropped.
    assert result.meta["primary_step"] == "orders"
    assert result.meta["step_count"] == 2
    assert set(result.meta["steps"]) == {"user", "orders"}
    user_rows = result.meta["steps"]["user"]["rows"]
    assert [{k: v for k, v in r.items() if not k.startswith("_")} for r in user_rows] == rows_a
