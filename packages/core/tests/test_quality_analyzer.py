"""Tests for the description quality analyzer."""

from __future__ import annotations

from elliot_core.eval.quality import (
    analyze_connector_quality,
    analyze_tool_quality,
)
from elliot_core.types.connector import ConnectorConfig
from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import ParameterDefinition, ToolDefinition


def _make_tool(
    tool_id: str = "get_users",
    description: str = "Returns all users in the system",
    params: list[ParameterDefinition] | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        id=tool_id,
        name=tool_id,
        description=description,
        category="READ",
        source_ids=["src"],
        parameters=params or [],
    )


def _described_param(name: str) -> ParameterDefinition:
    return ParameterDefinition(name=name, type="string", required=True, description="A value")


def _undescribed_param(name: str) -> ParameterDefinition:
    return ParameterDefinition(name=name, type="string", required=True, description="")


# ── min_length ────────────────────────────────────────────────────────────────


def test_short_description_fails_min_length():
    tool = _make_tool(description="Too short")
    result = analyze_tool_quality(tool)
    checks = [i.check for i in result.issues]
    assert "min_length" in checks
    assert any(i.severity == "error" for i in result.issues if i.check == "min_length")


def test_long_enough_description_no_min_length_issue():
    tool = _make_tool(description="Returns all users in the system sorted by name")
    result = analyze_tool_quality(tool)
    assert not any(i.check == "min_length" for i in result.issues)


# ── starts_with_verb ──────────────────────────────────────────────────────────


def test_description_not_starting_with_verb_warns():
    tool = _make_tool(description="All users in the system are returned here")
    result = analyze_tool_quality(tool)
    assert any(i.check == "starts_with_verb" for i in result.issues)


def test_description_starting_with_verb_no_warning():
    tool = _make_tool(description="Returns all users in the system sorted by name")
    result = analyze_tool_quality(tool)
    assert not any(i.check == "starts_with_verb" for i in result.issues)


# ── no_jargon ─────────────────────────────────────────────────────────────────


def test_sql_query_description_fails_jargon_and_verb():
    tool = _make_tool(description="SQL query for users in the database table")
    result = analyze_tool_quality(tool)
    checks = [i.check for i in result.issues]
    assert "no_jargon" in checks
    assert "starts_with_verb" in checks


def test_clean_description_no_jargon():
    tool = _make_tool(description="Returns all active users sorted by creation date")
    result = analyze_tool_quality(tool)
    assert not any(i.check == "no_jargon" for i in result.issues)


# ── has_params_described ──────────────────────────────────────────────────────


def test_param_with_no_description_fails():
    tool = _make_tool(
        description="Returns all users in the system",
        params=[_undescribed_param("user_id")],
    )
    result = analyze_tool_quality(tool)
    assert any(i.check == "has_params_described" and "user_id" in i.message for i in result.issues)


def test_param_with_description_no_issue():
    tool = _make_tool(
        description="Returns all users in the system",
        params=[_described_param("user_id")],
    )
    result = analyze_tool_quality(tool)
    assert not any(i.check == "has_params_described" for i in result.issues)


# ── name_snake_case ───────────────────────────────────────────────────────────


def test_camel_case_id_fails_snake_check():
    tool = _make_tool(tool_id="getUsers")
    result = analyze_tool_quality(tool)
    assert any(i.check == "name_snake_case" for i in result.issues)


def test_valid_snake_case_id_no_issue():
    tool = _make_tool(tool_id="get_users")
    result = analyze_tool_quality(tool)
    assert not any(i.check == "name_snake_case" for i in result.issues)


# ── no_generic_names ──────────────────────────────────────────────────────────


def test_generic_id_warns():
    tool = _make_tool(tool_id="query")
    result = analyze_tool_quality(tool)
    assert any(i.check == "no_generic_names" for i in result.issues)


# ── perfect tool scores 100 ───────────────────────────────────────────────────


def test_well_described_tool_scores_100():
    tool = _make_tool(
        tool_id="get_active_users",
        description="Returns all active users sorted by creation date in ascending order",
        params=[_described_param("status"), _described_param("limit")],
    )
    result = analyze_tool_quality(tool)
    assert result.issues == []
    assert result.score == 100.0


# ── analyze_connector_quality ─────────────────────────────────────────────────


def test_connector_overall_score_is_average_of_tool_scores():
    source = SourceConfig(id="src", name="Src", type="rest", url="https://example.com")
    t1 = _make_tool(
        tool_id="get_active_users",
        description="Returns all active users sorted by creation date in ascending order",
    )
    t2 = _make_tool(description="Too short")
    config = ConnectorConfig(
        name="c", slug="c", version="1", description="", sources=[source], tools=[t1, t2]
    )
    result = analyze_connector_quality(config)

    s1 = analyze_tool_quality(t1).score
    s2 = analyze_tool_quality(t2).score
    expected = round((s1 + s2) / 2, 1)
    assert result.overall_score == expected


def test_connector_empty_tools_scores_100():
    source = SourceConfig(id="src", name="Src", type="rest", url="https://example.com")
    config = ConnectorConfig(
        name="c", slug="c", version="1", description="", sources=[source], tools=[]
    )
    result = analyze_connector_quality(config)
    assert result.overall_score == 100.0


def test_connector_counts_errors_and_warnings():
    source = SourceConfig(id="src", name="Src", type="rest", url="https://example.com")
    tool = _make_tool(description="Too short", params=[_undescribed_param("x")])
    config = ConnectorConfig(
        name="c", slug="c", version="1", description="", sources=[source], tools=[tool]
    )
    result = analyze_connector_quality(config)
    assert result.error_count > 0
