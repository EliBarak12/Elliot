"""Tests for the ConnectorConfig static linter."""

from __future__ import annotations

from elliot_core.linter import lint_connector
from elliot_core.types import ConnectorConfig


def _make_connector(**tool_overrides) -> ConnectorConfig:  # type: ignore[type-arg]
    tool = {
        "id": "list_items",
        "name": "List Items",
        "description": "Return all items from the items table",
        "category": "READ",
        "source_ids": [],
        "sql": "SELECT id, name FROM items WHERE (:filter IS NULL OR name = :filter)",
        "parameters": [
            {
                "name": "filter",
                "type": "string",
                "required": False,
                "description": "Optional name filter",
            }
        ],
    }
    tool.update(tool_overrides)
    return ConnectorConfig(
        name="Test",
        slug="test",
        version="1.0.0",
        sources=[],
        tools=[tool],  # type: ignore[list-item]
    )


def test_clean_connector_has_no_errors() -> None:
    config = _make_connector()
    issues = lint_connector(config)
    assert not any(i.severity == "ERROR" for i in issues)


def test_short_description_is_error() -> None:
    config = _make_connector(description="Get it")
    issues = lint_connector(config)
    assert any(i.code == "DESCRIPTION_TOO_SHORT" for i in issues)
    assert any(i.severity == "ERROR" for i in issues if i.code == "DESCRIPTION_TOO_SHORT")


def test_description_missing_verb_is_warn() -> None:
    config = _make_connector(description="All items from the items table here")
    issues = lint_connector(config)
    assert any(i.code == "DESCRIPTION_MISSING_VERB" for i in issues)
    assert any(i.severity == "WARN" for i in issues if i.code == "DESCRIPTION_MISSING_VERB")


def test_unbounded_select_is_error() -> None:
    config = _make_connector(sql="SELECT * FROM items")
    issues = lint_connector(config)
    assert any(i.code == "UNBOUNDED_SELECT" for i in issues)
    assert any(i.severity == "ERROR" for i in issues if i.code == "UNBOUNDED_SELECT")


def test_select_star_with_where_no_limit_is_warn() -> None:
    config = _make_connector(sql="SELECT * FROM items WHERE active = 1")
    issues = lint_connector(config)
    assert any(i.code == "SELECT_STAR_NO_LIMIT" for i in issues)
    assert any(i.severity == "WARN" for i in issues if i.code == "SELECT_STAR_NO_LIMIT")


def test_select_star_with_limit_no_issue() -> None:
    config = _make_connector(sql="SELECT * FROM items LIMIT 50")
    issues = lint_connector(config)
    assert not any(i.code in ("UNBOUNDED_SELECT", "SELECT_STAR_NO_LIMIT") for i in issues)


def test_limit_lookalike_column_still_flags_unbounded() -> None:
    """A column named rate_limit must not be mistaken for a real LIMIT clause."""
    config = _make_connector(sql="SELECT * FROM items ORDER BY rate_limit")
    issues = lint_connector(config)
    assert any(i.code == "UNBOUNDED_SELECT" for i in issues)


def test_short_parameter_name_is_warn() -> None:
    config = _make_connector(
        parameters=[
            {
                "name": "id",
                "type": "string",
                "required": False,
                "description": "The item id filter",
            }
        ]
    )
    issues = lint_connector(config)
    assert any(i.code == "PARAMETER_NAME_TOO_SHORT" for i in issues)


def test_missing_parameter_description_is_warn() -> None:
    config = _make_connector(
        parameters=[
            {
                "name": "filter_val",
                "type": "string",
                "required": False,
                "description": "",
            }
        ]
    )
    issues = lint_connector(config)
    assert any(i.code == "PARAMETER_MISSING_DESCRIPTION" for i in issues)


def test_write_tool_without_mutation_verb_is_info() -> None:
    config = _make_connector(
        category="WRITE",
        description="Processes a new entry in the system table",
    )
    issues = lint_connector(config)
    assert any(i.code == "WRITE_TOOL_DESCRIPTION" for i in issues)
    assert any(i.severity == "INFO" for i in issues if i.code == "WRITE_TOOL_DESCRIPTION")


def test_write_tool_with_mutation_verb_no_info() -> None:
    config = _make_connector(
        category="WRITE",
        description="Create a new entry in the system table",
    )
    issues = lint_connector(config)
    assert not any(i.code == "WRITE_TOOL_DESCRIPTION" for i in issues)


def test_no_tools_returns_empty_issues() -> None:
    config = ConnectorConfig(
        name="Empty",
        slug="empty",
        version="1.0.0",
        sources=[],
        tools=[],
    )
    assert lint_connector(config) == []


def test_secret_in_url_is_error() -> None:
    from elliot_core.types.source import AuthConfig, SourceConfig

    source = SourceConfig(
        id="leaky",
        name="Leaky API",
        type="rest",
        url="https://api.example.com?key=supersecret",
        auth=AuthConfig(type="api_key", secret_key="supersecret"),
    )
    config = ConnectorConfig(
        name="Test",
        slug="test",
        version="1.0.0",
        sources=[source],
        tools=[],
    )
    issues = lint_connector(config)
    assert any(i.code == "SECRET_IN_URL" for i in issues)


# ── upgraded best-practice rules ─────────────────────────────────────────────


def _tool(tool_id: str, **overrides):  # type: ignore[no-untyped-def]
    base = {
        "id": tool_id,
        "name": tool_id.replace("_", " ").title(),
        "description": f"Return rows from the {tool_id} table for agents",
        "category": "READ",
        "sql": f"SELECT id FROM {tool_id} LIMIT 20",
        "parameters": [],
    }
    base.update(overrides)
    return base


def test_too_many_tools_is_warn() -> None:
    tools = [_tool(f"list_table_{i}") for i in range(26)]
    config = ConnectorConfig(name="Big", slug="big", version="1.0.0", tools=tools)
    issues = lint_connector(config)
    assert any(i.code == "TOO_MANY_TOOLS" for i in issues)


def test_duplicate_tool_id_is_error() -> None:
    config = ConnectorConfig(
        name="Dup",
        slug="dup",
        version="1.0.0",
        tools=[_tool("list_items"), _tool("list_items")],
    )
    issues = lint_connector(config)
    assert any(i.code == "DUPLICATE_TOOL_ID" and i.severity == "ERROR" for i in issues)


def test_generic_param_name_is_warn() -> None:
    config = _make_connector(
        parameters=[
            {"name": "data", "type": "string", "required": False, "description": "some value"}
        ]
    )
    issues = lint_connector(config)
    assert any(i.code == "PARAMETER_NAME_GENERIC" for i in issues)


def test_enum_candidate_param_is_warn() -> None:
    config = _make_connector(
        parameters=[
            {
                "name": "order_status",
                "type": "string",
                "required": False,
                "description": "The status, must be active or closed",
            }
        ]
    )
    issues = lint_connector(config)
    assert any(i.code == "PARAMETER_SHOULD_BE_ENUM" for i in issues)


def test_enum_param_with_enum_set_no_issue() -> None:
    config = _make_connector(
        parameters=[
            {
                "name": "order_status",
                "type": "string",
                "required": False,
                "description": "The status, must be active or closed",
                "enum": ["active", "closed"],
            }
        ]
    )
    issues = lint_connector(config)
    assert not any(i.code == "PARAMETER_SHOULD_BE_ENUM" for i in issues)


def test_missing_pagination_is_warn() -> None:
    config = ConnectorConfig(
        name="P",
        slug="p",
        version="1.0.0",
        tools=[_tool("list_things", sql="SELECT id FROM things")],
    )
    issues = lint_connector(config)
    assert any(i.code == "MISSING_PAGINATION" for i in issues)


def test_pagination_with_limit_param_no_issue() -> None:
    config = ConnectorConfig(
        name="P",
        slug="p",
        version="1.0.0",
        tools=[
            _tool(
                "list_things",
                sql="SELECT id FROM things",
                parameters=[
                    {
                        "name": "limit",
                        "type": "integer",
                        "required": False,
                        "description": "Max rows to return",
                    }
                ],
            )
        ],
    )
    issues = lint_connector(config)
    assert not any(i.code == "MISSING_PAGINATION" for i in issues)


def test_sensitive_field_exposed_is_error() -> None:
    config = ConnectorConfig(
        name="S",
        slug="s",
        version="1.0.0",
        tools=[_tool("list_users", sql="SELECT id, ssn FROM users LIMIT 20")],
    )
    issues = lint_connector(config, sensitive_fields=["ssn"])
    assert any(i.code == "SENSITIVE_FIELD_EXPOSED" and i.severity == "ERROR" for i in issues)


def test_sensitive_field_not_passed_no_issue() -> None:
    config = ConnectorConfig(
        name="S",
        slug="s",
        version="1.0.0",
        tools=[_tool("list_users", sql="SELECT id, ssn FROM users LIMIT 20")],
    )
    issues = lint_connector(config)
    assert not any(i.code == "SENSITIVE_FIELD_EXPOSED" for i in issues)
