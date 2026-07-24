"""Tests for the product-aware MCP ``instructions`` briefing a consuming agent
reads on connect (``derive_agent_briefing``).

The briefing is Elliot's one leveraged place to orient the agent: it must name
the product, split READ (context) from WRITE/ACTION (operate), and flag only the
true danger zone — never additive creates/updates.
"""

from __future__ import annotations

from elliot_connector_runtime.server import derive_agent_briefing
from elliot_core.types import (
    ApiRequestMapping,
    ConnectorConfig,
    ParameterDefinition,
    SourceConfig,
    ToolDefinition,
)


def _source() -> SourceConfig:
    return SourceConfig(id="orders", name="Orders API", type="rest", url="https://api.x.com")


def _read(tool_id: str = "list_orders") -> ToolDefinition:
    return ToolDefinition(
        id=tool_id,
        name=tool_id.replace("_", " ").title(),
        description="List orders.",
        category="READ",
        sql='SELECT id FROM "orders"',
        source_ids=["orders"],
    )


def _action(
    tool_id: str, *, category: str = "WRITE", destructive: bool | None = None
) -> ToolDefinition:
    return ToolDefinition(
        id=tool_id,
        name=tool_id.replace("_", " ").title(),
        description=f"{tool_id.split('_')[0].title()} an order.",
        category=category,
        api_mapping=ApiRequestMapping(method="POST", body_params=["sku"]),
        parameters=[ParameterDefinition(name="sku", type="string", required=True, description="")],
        source_ids=["orders"],
        destructive=destructive,
    )


def _connector(tools: list[ToolDefinition], **kw: object) -> ConnectorConfig:
    return ConnectorConfig(
        name=kw.get("name", "acme-orders"),  # type: ignore[arg-type]
        slug="acme-orders",
        version="1.0.0",
        description=kw.get("description", ""),  # type: ignore[arg-type]
        sources=[_source()],
        tools=tools,
        skills=kw.get("skills", []),  # type: ignore[arg-type]
    )


def test_briefing_leads_with_product_name_and_description() -> None:
    text = derive_agent_briefing(
        _connector([_read()], description="Order management for online sellers")
    )
    assert "acme-orders" in text
    assert "Order management for online sellers" in text


def test_frames_read_as_context_and_action_as_operate() -> None:
    text = derive_agent_briefing(_connector([_read(), _action("create_order")]))
    assert "1 READ tool(s) give you context" in text
    assert "1 WRITE/ACTION tool(s) operate the product" in text


def test_danger_zone_names_destructive_verb_tools_only() -> None:
    text = derive_agent_briefing(_connector([_action("delete_order"), _action("create_order")]))
    assert "Danger zone: 1 tool(s) are irreversible" in text
    assert "delete_order" in text
    # An additive create is NOT the danger zone — it must not be named there.
    danger_line = next(line for line in text.splitlines() if line.startswith("Danger zone"))
    assert "create_order" not in danger_line


def test_explicit_destructive_flag_enters_danger_zone_without_a_verb() -> None:
    # execute_refund carries no delete/remove/... verb — only the flag gates it.
    text = derive_agent_briefing(
        _connector([_action("execute_refund", category="ACTION", destructive=True)])
    )
    assert "Danger zone: 1 tool(s) are irreversible" in text
    assert "execute_refund" in text


def test_additive_only_connector_has_no_danger_zone() -> None:
    text = derive_agent_briefing(_connector([_read(), _action("create_order")]))
    assert "Danger zone" not in text


def test_read_only_connector_reads_as_context_only() -> None:
    text = derive_agent_briefing(_connector([_read("list_orders"), _read("get_order")]))
    assert "2 READ tool(s) give you context" in text
    assert "WRITE/ACTION" not in text
    assert "Danger zone" not in text


def test_deterministic_skill_briefed_as_a_one_call_workflow() -> None:
    from elliot_core.types import SkillDefinition, SkillStep

    skill = SkillDefinition(
        id="reorder",
        name="Reorder",
        description="Reorder a past order.",
        steps=[SkillStep(alias="place", tool_id="create_order", params={})],
    )
    text = derive_agent_briefing(_connector([_read(), _action("create_order")], skills=[skill]))
    # A skill with steps is now a callable tool — the briefing must say so.
    assert "1 multi-step workflow(s) run in ONE call" in text
    assert "MCP prompts" not in text


def test_prose_skill_briefed_as_a_prompt() -> None:
    from elliot_core.types import SkillDefinition

    skill = SkillDefinition(
        id="triage",
        name="Triage",
        description="How to triage an incident.",
        instructions="Assess severity, then page the on-call.",
    )
    text = derive_agent_briefing(_connector([_read()], skills=[skill]))
    assert "1 prose workflow(s) are available as MCP prompts" in text
    assert "run in ONE call" not in text


def test_falls_back_gracefully_with_no_tools() -> None:
    text = derive_agent_briefing(_connector([]))
    assert "acme-orders" in text
    assert "Call list_tools" in text
