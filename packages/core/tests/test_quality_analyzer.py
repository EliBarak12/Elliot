"""Tests for the description quality analyzer."""

from __future__ import annotations

from elliot_core.eval.quality import (
    BEST_PRACTICES,
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


# ── mcp-builder best-practice tagging ──────────────────────────────────────────


def test_every_issue_carries_a_known_principle():
    known = {bp["id"] for bp in BEST_PRACTICES}
    tool = _make_tool(
        tool_id="getData",  # snake_case + generic
        description="SQL table dump",  # short + jargon + no verb
        params=[_undescribed_param("data")],
    )
    result = analyze_tool_quality(tool)
    assert result.issues  # sanity: this tool is genuinely bad
    for issue in result.issues:
        assert issue.principle in known


def test_min_length_tagged_context_and_params_tagged_schema():
    tool = _make_tool(description="Too short", params=[_undescribed_param("user_id")])
    by_check = {i.check: i.principle for i in analyze_tool_quality(tool).issues}
    assert by_check["min_length"] == "context"
    assert by_check["has_params_described"] == "schema"


# ── enum_for_closed_set ─────────────────────────────────────────────────────────


def test_closed_value_set_string_param_warns_to_use_enum():
    tool = _make_tool(
        description="Returns orders filtered by their current status value",
        params=[
            ParameterDefinition(
                name="order_status",
                type="string",
                required=True,
                description="The status, must be one of open, closed, or pending",
            )
        ],
    )
    result = analyze_tool_quality(tool)
    issue = next((i for i in result.issues if i.check == "enum_for_closed_set"), None)
    assert issue is not None
    assert issue.principle == "schema"


def test_param_already_enum_no_enum_warning():
    tool = _make_tool(
        description="Returns orders filtered by their current status value",
        params=[
            ParameterDefinition(
                name="order_status",
                type="string",
                required=True,
                description="The status, must be one of open, closed, or pending",
                enum=["open", "closed", "pending"],
            )
        ],
    )
    result = analyze_tool_quality(tool)
    assert not any(i.check == "enum_for_closed_set" for i in result.issues)


# ── pagination ──────────────────────────────────────────────────────────────────


def test_unbounded_sql_list_tool_warns_pagination():
    tool = ToolDefinition(
        id="list_orders",
        name="list_orders",
        description="Returns every order placed by every customer",
        category="READ",
        source_ids=["src"],
        sql="SELECT id, total FROM orders",
    )
    result = analyze_tool_quality(tool)
    issue = next((i for i in result.issues if i.check == "pagination"), None)
    assert issue is not None
    assert issue.principle == "context"


def test_sql_list_tool_with_limit_no_pagination_warning():
    tool = ToolDefinition(
        id="list_orders",
        name="list_orders",
        description="Returns recent orders placed by every customer",
        category="READ",
        source_ids=["src"],
        sql="SELECT id, total FROM orders LIMIT 50",
    )
    result = analyze_tool_quality(tool)
    assert not any(i.check == "pagination" for i in result.issues)


# ── mutation_hint ────────────────────────────────────────────────────────────────


def test_write_tool_without_mutation_word_warns():
    tool = ToolDefinition(
        id="register_customer",
        name="register_customer",
        description="Registers a brand new customer in the billing system",
        category="WRITE",
        source_ids=["src"],
    )
    result = analyze_tool_quality(tool)
    issue = next((i for i in result.issues if i.check == "mutation_hint"), None)
    assert issue is not None
    assert issue.principle == "annotations"


def test_write_tool_with_mutation_word_no_warning():
    tool = ToolDefinition(
        id="create_customer",
        name="create_customer",
        description="Creates a brand new customer record in the billing system",
        category="WRITE",
        source_ids=["src"],
    )
    result = analyze_tool_quality(tool)
    assert not any(i.check == "mutation_hint" for i in result.issues)


# ── danger_zone_classified ──────────────────────────────────────────────────────


def test_unclassified_high_impact_action_warns():
    # A high-impact verb (cancel/refund/…) the runtime doesn't auto-detect, left
    # unclassified — the quality score should reflect the ungated danger zone.
    tool = ToolDefinition(
        id="cancel_subscription",
        name="cancel_subscription",
        description="Cancels the customer's active subscription immediately",
        category="ACTION",
        source_ids=["src"],
    )
    result = analyze_tool_quality(tool)
    issue = next((i for i in result.issues if i.check == "danger_zone_classified"), None)
    assert issue is not None
    assert issue.principle == "annotations"


def test_classified_high_impact_action_no_warning():
    for flag in (True, False):
        tool = ToolDefinition(
            id="cancel_subscription",
            name="cancel_subscription",
            description="Cancels the customer's active subscription immediately",
            category="ACTION",
            source_ids=["src"],
            destructive=flag,
        )
        result = analyze_tool_quality(tool)
        assert not any(i.check == "danger_zone_classified" for i in result.issues), flag


def test_additive_action_no_danger_zone_check():
    # create_* has no high-impact verb — the check doesn't apply (no false warn).
    tool = ToolDefinition(
        id="create_invoice",
        name="create_invoice",
        description="Creates a new invoice for a customer",
        category="ACTION",
        source_ids=["src"],
    )
    result = analyze_tool_quality(tool)
    assert not any(i.check == "danger_zone_classified" for i in result.issues)


def test_high_impact_verb_in_description_counts_as_naming_the_mutation():
    """An irreversible verb IS the mutation, and used not to count as one.

    The base word set named the ordinary mutations and none of the dangerous
    ones, so the tools the check exists to protect an agent from were the tools
    it could not recognise. `cancel_order` described as "Cancels an order by id.
    Irreversible." was told its description "doesn't mention the mutation" while
    danger_zone_classified passed the same tool as destructive: true.
    """
    for description in (
        "Cancels an order by id. Irreversible.",
        "Refunds a payment to the original card.",
        "Suspends the user account until an admin restores it.",
        "Unpublishes the connector from its live URL.",
    ):
        tool = ToolDefinition(
            id="cancel_order",
            name="cancel_order",
            description=description,
            category="ACTION",
            source_ids=["src"],
            destructive=True,
        )
        result = analyze_tool_quality(tool)
        assert not any(i.check == "mutation_hint" for i in result.issues), description


def test_mutation_word_must_start_a_word():
    """`ban` and `void` are short enough that a substring test misfires.

    "Abandons" and "Avoids" each contain one mid-word; neither names a mutation.
    """
    for description in ("Abandons the draft and starts over.", "Avoids duplicate rows."):
        tool = ToolDefinition(
            id="handle_draft",
            name="handle_draft",
            description=description,
            category="WRITE",
            source_ids=["src"],
        )
        result = analyze_tool_quality(tool)
        assert any(i.check == "mutation_hint" for i in result.issues), description


def test_high_impact_verb_starts_a_description():
    """The verb block was written for mutation verbs and got only "cancel".

    "refund", "void", "suspend", "terminate", "deactivate" and the rest of
    HIGH_IMPACT_VERBS were absent, so the most consequential actions a connector
    can expose were the ones told their description does not start with an
    action verb — by the quality scan and, off the same pattern, by the linter.
    """
    for description in (
        "Refunds a payment to the original card.",
        "Voids the invoice so it can never be paid.",
        "Suspends the user account until an admin restores it.",
        "Terminates the running deployment.",
        "Unpublishes the connector from its live URL.",
    ):
        tool = ToolDefinition(
            id="refund_payment",
            name="refund_payment",
            description=description,
            category="ACTION",
            source_ids=["src"],
            destructive=True,
        )
        result = analyze_tool_quality(tool)
        assert not any(i.check == "starts_with_verb" for i in result.issues), description


def test_short_verb_must_start_a_word_boundary():
    """`ban` and `void` are short; the trailing \\b keeps them from over-matching."""
    tool = ToolDefinition(
        id="show_banner",
        name="show_banner",
        description="Banner ads for the storefront, by placement.",
        category="READ",
        source_ids=["src"],
    )
    result = analyze_tool_quality(tool)
    assert any(i.check == "starts_with_verb" for i in result.issues)


def test_jargon_is_found_when_it_ends_a_clause():
    """`.split()` left the punctuation attached, so "table." was not "table".

    A description names its noun last far more often than mid-sentence, so the
    common shape of leaked jargon was the one shape that slipped through.
    """
    for description, word in (
        ("Returns rows from the orders table.", "table"),
        ("Returns rows from the orders table, newest first.", "table"),
        ("Returns the customer records from the API.", "api"),
        ("Returns everything stored in the database.", "database"),
        ("Runs the statement against the endpoint.", "endpoint"),
        ("Returns rows using SQL.", "sql"),
    ):
        tool = ToolDefinition(
            id="list_rows",
            name="list_rows",
            description=description,
            category="READ",
            source_ids=["src"],
        )
        result = analyze_tool_quality(tool)
        issue = next((i for i in result.issues if i.check == "no_jargon"), None)
        assert issue is not None, description
        assert word in issue.message, description


def test_jargon_does_not_match_inside_a_longer_word():
    """Tokenising on word characters keeps "timetable" from reading as "table"."""
    tool = ToolDefinition(
        id="list_departures",
        name="list_departures",
        description="Returns the timetable for the depot.",
        category="READ",
        source_ids=["src"],
    )
    result = analyze_tool_quality(tool)
    assert not any(i.check == "no_jargon" for i in result.issues)
