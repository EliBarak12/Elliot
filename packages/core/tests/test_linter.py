"""Tests for the ConnectorConfig static linter."""

from __future__ import annotations

from elliot_core.linter import lint_connector
from elliot_core.types import ConnectorConfig, SourceConfig


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
                "description": "Optional exact-match name filter",
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


def test_filter_param_without_semantics_is_warn() -> None:
    config = _make_connector(
        parameters=[
            {
                "name": "name_filter",
                "type": "string",
                "required": False,
                "description": "Filter results by name",
            }
        ]
    )
    issues = lint_connector(config)
    assert any(i.code == "FILTER_SEMANTICS_UNCLEAR" and i.severity == "WARN" for i in issues)


def test_filter_param_with_semantics_no_issue() -> None:
    config = _make_connector(
        parameters=[
            {
                "name": "name_filter",
                "type": "string",
                "required": False,
                "description": "Substring (case-insensitive) match on the item name",
            }
        ]
    )
    issues = lint_connector(config)
    assert not any(i.code == "FILTER_SEMANTICS_UNCLEAR" for i in issues)


def test_short_description_is_error() -> None:
    config = _make_connector(description="Get it")
    issues = lint_connector(config)
    assert any(i.code == "DESCRIPTION_TOO_SHORT" for i in issues)
    assert any(i.severity == "ERROR" for i in issues if i.code == "DESCRIPTION_TOO_SHORT")


# ── TOOL_SOURCE_NOT_LOADED: SQL ↔ source_ids coverage ────────────────────────


def _catalog_source() -> SourceConfig:
    return SourceConfig(
        id="catalog_a",
        name="catalog_a",
        type="rest",
        url="https://data.gov.il/api/3/action/package_search",
        table_name="catalog_a",
    )


def _search_tool(source_ids: list[str]) -> dict:  # type: ignore[type-arg]
    return {
        "id": "search_datasets",
        "name": "search_datasets",
        "description": "Search the catalog for datasets by keyword",
        "category": "READ",
        "source_ids": source_ids,
        "sql": 'SELECT id, title FROM "catalog_a_result_results" WHERE title LIKE :q LIMIT 10',
        "parameters": [
            {"name": "q", "type": "string", "required": True, "description": "search text"}
        ],
    }


def test_tool_referencing_source_missing_from_source_ids_is_error() -> None:
    # SQL touches catalog_a's flattened child table, but source_ids is empty —
    # the runtime would never materialize it (the data.gov.il regression).
    config = ConnectorConfig(
        name="T",
        slug="t",
        version="1.0.0",
        sources=[_catalog_source()],
        tools=[_search_tool(source_ids=[])],  # type: ignore[list-item]
    )
    issues = lint_connector(config)
    mismatch = [i for i in issues if i.code == "TOOL_SOURCE_NOT_LOADED"]
    assert mismatch and mismatch[0].severity == "ERROR"


def test_tool_with_matching_source_ids_is_clean() -> None:
    config = ConnectorConfig(
        name="T",
        slug="t",
        version="1.0.0",
        sources=[_catalog_source()],
        tools=[_search_tool(source_ids=["catalog_a"])],  # type: ignore[list-item]
    )
    codes = {i.code for i in lint_connector(config)}
    assert "TOOL_SOURCE_NOT_LOADED" not in codes


def test_cte_alias_is_not_flagged_as_missing_source() -> None:
    # "ds" is a CTE alias, not a source — it must not trigger the rule.
    tool = {
        "id": "list_publishers",
        "name": "list_publishers",
        "description": "List dataset publishers with counts",
        "category": "READ",
        "source_ids": ["catalog_a"],
        "sql": (
            "WITH ds AS (SELECT organization_title AS publisher "
            'FROM "catalog_a_result_results") '
            "SELECT publisher, COUNT(*) AS n FROM ds GROUP BY publisher LIMIT 50"
        ),
        "parameters": [],
    }
    config = ConnectorConfig(
        name="T",
        slug="t",
        version="1.0.0",
        sources=[_catalog_source()],
        tools=[tool],  # type: ignore[list-item]
    )
    codes = {i.code for i in lint_connector(config)}
    assert "TOOL_SOURCE_NOT_LOADED" not in codes


def test_description_missing_verb_is_warn() -> None:
    config = _make_connector(description="All items from the items table here")
    issues = lint_connector(config)
    assert any(i.code == "DESCRIPTION_MISSING_VERB" for i in issues)
    assert any(i.severity == "WARN" for i in issues if i.code == "DESCRIPTION_MISSING_VERB")


def test_third_person_descriptions_are_not_flagged() -> None:
    # Third-person-singular present is the standard professional style and is
    # exactly what the linter's own WRITE_TOOL_DESCRIPTION suggestion recommends
    # ("Creates...", "Deletes...", "Sends..."). Flagging it contradicted our own
    # advice and the quality scan; lock the accepted forms in. Includes the
    # sibilant "-es" verbs (Fetches/Searches) that a bare "s?" would miss.
    for description in (
        "Returns the top N products by revenue",
        "Lists all active customers",
        "Creates a new order for a customer",
        "Deletes a customer by id",
        "Sends a notification email",
        "Fetches the latest invoice for an account",
        "Searches orders by status and date",
        "Updates a record in place",
    ):
        config = _make_connector(description=description)
        issues = lint_connector(config)
        assert not any(i.code == "DESCRIPTION_MISSING_VERB" for i in issues), description


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


def test_sensitive_field_in_write_api_mapping_is_error() -> None:
    # A WRITE tool moves fields through api_mapping, not SQL — the SQL-only
    # haystack used to miss a never-expose field forwarded in the request body.
    config = ConnectorConfig(
        name="S",
        slug="s",
        version="1.0.0",
        tools=[
            _tool(
                "update_user",
                category="WRITE",
                description="Update a user record in the users table",
                sql=None,
                api_mapping={
                    "method": "POST",
                    "path_template": "/users",
                    "body_params": ["ssn"],
                },
            )
        ],
    )
    issues = lint_connector(config, sensitive_fields=["ssn"])
    assert any(i.code == "SENSITIVE_FIELD_EXPOSED" and i.severity == "ERROR" for i in issues)


def test_sensitive_field_in_passthrough_query_params_is_error() -> None:
    # A READ passthrough tool forwards rest_query_params straight to the
    # upstream — a never-expose field there must be flagged just like a SELECT.
    config = ConnectorConfig(
        name="S",
        slug="s",
        version="1.0.0",
        sources=[
            SourceConfig(id="api", name="API", type="rest", url="https://api.example.com/users")
        ],
        tools=[_tool("search_users", sql=None, source_ids=["api"], rest_query_params=["ssn"])],
    )
    issues = lint_connector(config, sensitive_fields=["ssn"])
    assert any(i.code == "SENSITIVE_FIELD_EXPOSED" and i.severity == "ERROR" for i in issues)


def test_forwarded_passthrough_param_names_are_exempt() -> None:
    # ``q`` and ``key`` are CKAN/BoI's real param names; renaming them breaks
    # the forwarded call, so the name rules must not flag them (P2).
    config = ConnectorConfig(
        name="Test",
        slug="test",
        version="1.0.0",
        sources=[SourceConfig(id="ckan", name="ckan", type="rest", url="https://x/api")],
        tools=[
            {  # type: ignore[list-item]
                "id": "search_datasets",
                "name": "Search datasets",
                "description": "Search datasets via the CKAN passthrough.",
                "category": "READ",
                "source_ids": ["ckan"],
                "rest_query_params": ["q", "key"],
                "parameters": [
                    {"name": "q", "type": "string", "description": "Full-text search (substring)."},
                    {"name": "key", "type": "string", "description": "CKAN API key for the call."},
                ],
            }
        ],
    )
    codes = {i.code for i in lint_connector(config)}
    assert "PARAMETER_NAME_TOO_SHORT" not in codes
    assert "PARAMETER_NAME_GENERIC" not in codes


def test_non_forwarded_short_and_generic_names_still_flagged() -> None:
    config = _make_connector(
        sql="SELECT id FROM items WHERE id = :q AND k = :key",
        parameters=[
            {"name": "q", "type": "string", "description": "Some search value here."},
            {"name": "key", "type": "string", "description": "Some generic key value."},
        ],
    )
    codes = {i.code for i in lint_connector(config)}
    assert "PARAMETER_NAME_TOO_SHORT" in codes  # q
    assert "PARAMETER_NAME_GENERIC" in codes  # key


def test_description_mutation_verbs_pass() -> None:
    # ACTION tools naturally open with mutation verbs; none of these should
    # be told to rewrite as "Return...".
    for desc in (
        "Add a note to a helpdesk ticket on the customer's behalf.",
        "Cancel an order by id, notifying the customer.",
        "Escalates the ticket to the on-call engineer.",
        "Mark a conversation as resolved.",
    ):
        config = _make_connector(description=desc)
        codes = {i.code for i in lint_connector(config)}
        assert "DESCRIPTION_MISSING_VERB" not in codes, desc


# ── skill executability (F4: a deterministic skill that can never run) ────────

_GET_ORDER = {
    "id": "get_order",
    "name": "Get order",
    "description": "Return a single order by its id",
    "category": "READ",
    "source_ids": [],
    "sql": "SELECT * FROM orders WHERE id = :order_id",
    "parameters": [
        {"name": "order_id", "type": "integer", "required": True, "description": "Order id"}
    ],
}


def _with_skill(skill: dict) -> ConnectorConfig:  # type: ignore[type-arg]
    return ConnectorConfig(
        name="T",
        slug="t",
        version="1.0.0",
        sources=[],
        tools=[_GET_ORDER],  # type: ignore[list-item]
        skills=[skill],  # type: ignore[list-item]
    )


def _skill_codes(config: ConnectorConfig) -> set[str]:
    return {i.code for i in lint_connector(config) if i.code.startswith("SKILL_")}


def test_skill_step_unknown_tool_is_error() -> None:
    config = _with_skill(
        {
            "id": "s",
            "name": "S",
            "description": "A workflow",
            "steps": [{"alias": "a", "tool_id": "does_not_exist", "params": {}}],
        }
    )
    assert "SKILL_STEP_UNKNOWN_TOOL" in _skill_codes(config)


def test_skill_step_missing_required_param_is_error() -> None:
    # get_order needs order_id; the step binds nothing → dead on first call.
    config = _with_skill(
        {
            "id": "s",
            "name": "S",
            "description": "A workflow",
            "steps": [{"alias": "a", "tool_id": "get_order", "params": {}}],
        }
    )
    codes = _skill_codes(config)
    assert "SKILL_STEP_MISSING_PARAM" in codes
    assert all(
        i.severity == "ERROR"
        for i in lint_connector(config)
        if i.code == "SKILL_STEP_MISSING_PARAM"
    )


def test_skill_step_dangling_input_binding_is_error() -> None:
    # order_id IS bound (no MISSING_PARAM), but to an input the skill never declares.
    config = _with_skill(
        {
            "id": "s",
            "name": "S",
            "description": "A workflow",
            "steps": [
                {
                    "alias": "a",
                    "tool_id": "get_order",
                    "params": {"order_id": "{{ skill.input.oid }}"},
                }
            ],
        }
    )
    codes = _skill_codes(config)
    assert "SKILL_STEP_DANGLING_INPUT" in codes
    assert "SKILL_STEP_MISSING_PARAM" not in codes


def test_skill_step_bound_to_declared_input_is_clean() -> None:
    config = _with_skill(
        {
            "id": "s",
            "name": "S",
            "description": "A workflow",
            "input_parameters": [
                {"name": "oid", "type": "integer", "required": True, "description": "Order id"}
            ],
            "steps": [
                {
                    "alias": "a",
                    "tool_id": "get_order",
                    "params": {"order_id": "{{ skill.input.oid }}"},
                }
            ],
        }
    )
    assert _skill_codes(config) == set()


def test_prose_only_skill_is_not_step_linted() -> None:
    config = _with_skill(
        {
            "id": "p",
            "name": "P",
            "description": "A prose workflow",
            "instructions": "Look up the order, then summarise it for the user.",
        }
    )
    assert _skill_codes(config) == set()
