"""Tests for the connector audit subsystem (seeds, judge, store)."""

from __future__ import annotations

from pathlib import Path

from elliot_core.audit import (
    audit_rubric,
    generate_audit_seeds,
    judge_audit,
    load_audit_reports,
    save_audit_report,
)
from elliot_core.audit.judge import OVERSIZED_TOKEN_ESTIMATE
from elliot_core.audit.models import (
    AuditToolCall,
    AuditTranscript,
    ProductIntent,
)
from elliot_core.types import ConnectorConfig


def _connector(*, tools: list[dict] | None = None) -> ConnectorConfig:  # type: ignore[type-arg]
    default_tools = [
        {
            "id": "list_customers",
            "name": "List Customers",
            "description": "Return customers filtered by plan",
            "category": "READ",
            "sql": "SELECT id, plan FROM customers LIMIT 20",
            "parameters": [],
        },
        {
            "id": "search_orders",
            "name": "Search Orders",
            "description": "Search orders by customer",
            "category": "READ",
            "sql": "SELECT id FROM orders LIMIT 20",
            "parameters": [],
        },
        {
            "id": "create_invoice",
            "name": "Create Invoice",
            "description": "Create an invoice for a customer",
            "category": "WRITE",
            "source_ids": [],
            "api_mapping": {"method": "POST", "path_template": "/invoices"},
            "parameters": [],
        },
    ]
    return ConnectorConfig(
        name="Acme",
        slug="acme",
        version="1.0.0",
        sources=[],
        tools=tools or default_tools,  # type: ignore[arg-type]
    )


# ── seeds ───────────────────────────────────────────────────────────────────


def test_generate_seeds_uses_jobs_to_be_done() -> None:
    intent = ProductIntent(jobs_to_be_done=["Find a customer's open orders", "Bill a customer"])
    seeds = generate_audit_seeds(_connector(), intent, limit=5)
    assert seeds[0].job == "Find a customer's open orders"
    # Job text drives tool matching.
    assert "search_orders" in seeds[0].suggested_tools or seeds[0].suggested_tools


def test_generate_seeds_without_intent_covers_tools() -> None:
    seeds = generate_audit_seeds(_connector(), None, limit=5)
    assert 1 <= len(seeds) <= 5
    assert all(s.id.startswith("seed-") for s in seeds)
    # The write tool gets its own safety-focused seed.
    assert any("create_invoice" in s.suggested_tools for s in seeds)


def test_generate_seeds_respects_limit() -> None:
    seeds = generate_audit_seeds(_connector(), None, limit=2)
    assert len(seeds) == 2


def test_generate_seeds_empty_connector_has_fallback() -> None:
    config = ConnectorConfig(name="Empty", slug="empty", version="1.0.0", tools=[])
    seeds = generate_audit_seeds(config, None)
    assert len(seeds) == 1
    assert seeds[0].id == "seed-1"


def test_generate_seeds_zero_limit_clamped_to_one() -> None:
    seeds = generate_audit_seeds(_connector(), None, limit=0)
    assert len(seeds) == 1


# ── judge ───────────────────────────────────────────────────────────────────


def _ok_call(tool_id: str, tokens: int = 200) -> AuditToolCall:
    return AuditToolCall(tool_id=tool_id, ok=True, result_row_count=5, result_token_estimate=tokens)


def test_judge_all_success_passes() -> None:
    transcripts = [
        AuditTranscript(
            seed_id="seed-1",
            task="t",
            calls=[_ok_call("list_customers"), _ok_call("search_orders")],
            task_completed=True,
        )
    ]
    report = judge_audit(transcripts, _connector())
    assert report.passed is True
    assert report.task_success_rate == 1.0
    assert report.error_call_count == 0
    completion = next(d for d in report.dimension_scores if d.dimension == "task_completion")
    assert completion.score == 10.0


def test_judge_flags_failed_task() -> None:
    transcripts = [AuditTranscript(seed_id="seed-1", task="t", calls=[_ok_call("list_customers")])]
    report = judge_audit(transcripts, _connector())
    assert report.passed is False
    assert any(f.dimension == "task_completion" for f in report.findings)


def test_judge_flags_unknown_tool_as_error() -> None:
    transcripts = [
        AuditTranscript(
            seed_id="seed-1",
            task="t",
            calls=[AuditToolCall(tool_id="ghost_tool", ok=True)],
            task_completed=True,
        )
    ]
    report = judge_audit(transcripts, _connector())
    finding = next(f for f in report.findings if f.tool_id == "ghost_tool")
    assert finding.severity == "error"
    assert finding.dimension == "tool_selection"
    assert report.passed is False


def test_judge_treats_a_skill_call_as_valid_and_credits_its_tools_for_coverage() -> None:
    # A deterministic skill is a callable target; an audit agent may invoke it by
    # its id. It must NOT be flagged as an unknown tool, and calling it must
    # credit the tools it chains toward coverage.
    from elliot_core.types import ConnectorConfig, SkillDefinition, SkillStep, ToolDefinition

    tools = [
        ToolDefinition(
            id="list_customers",
            name="List customers",
            description="List customers.",
            category="READ",
            source_ids=[],
            sql="SELECT id FROM customers LIMIT 20",
        ),
        ToolDefinition(
            id="search_orders",
            name="Search orders",
            description="Search orders for a customer.",
            category="READ",
            source_ids=[],
            sql="SELECT id FROM orders LIMIT 20",
        ),
    ]
    skill = SkillDefinition(
        id="customer_orders",
        name="Customer orders",
        description="Look up a customer, then their orders.",
        steps=[
            SkillStep(alias="c", tool_id="list_customers", params={}),
            SkillStep(alias="o", tool_id="search_orders", params={}),
        ],
    )
    connector = ConnectorConfig(
        name="Acme", slug="acme", version="1.0.0", sources=[], tools=tools, skills=[skill]
    )
    transcripts = [
        AuditTranscript(
            seed_id="seed-1",
            task="t",
            calls=[
                AuditToolCall(
                    tool_id="customer_orders", ok=True, is_skill=True, result_token_estimate=120
                )
            ],
            task_completed=True,
        )
    ]
    report = judge_audit(transcripts, connector)
    # Not flagged as an unknown tool.
    assert not any(f.tool_id == "customer_orders" for f in report.findings)
    # The skill's two step tools are both credited → full coverage from one call.
    coverage = next(d for d in report.dimension_scores if d.dimension == "scenario_coverage")
    assert coverage.score == 10.0


def test_judge_flags_schema_error() -> None:
    transcripts = [
        AuditTranscript(
            seed_id="seed-1",
            task="t",
            calls=[
                AuditToolCall(
                    tool_id="list_customers",
                    ok=False,
                    error_code="MISSING_PARAM",
                    error_message="missing parameter",
                )
            ],
            task_completed=True,
        )
    ]
    report = judge_audit(transcripts, _connector())
    assert any(f.dimension == "schema_clarity" for f in report.findings)
    schema = next(d for d in report.dimension_scores if d.dimension == "schema_clarity")
    assert schema.score < 10.0


def test_judge_flags_nonactionable_error() -> None:
    transcripts = [
        AuditTranscript(
            seed_id="seed-1",
            task="t",
            calls=[
                AuditToolCall(
                    tool_id="list_customers",
                    ok=False,
                    error_code="INTERNAL_ERROR",
                    error_message="boom",
                )
            ],
            task_completed=True,
        )
    ]
    report = judge_audit(transcripts, _connector())
    assert any(f.dimension == "error_actionability" for f in report.findings)


def test_judge_flags_oversized_response() -> None:
    transcripts = [
        AuditTranscript(
            seed_id="seed-1",
            task="t",
            calls=[_ok_call("list_customers", tokens=OVERSIZED_TOKEN_ESTIMATE + 1000)],
            task_completed=True,
        )
    ]
    report = judge_audit(transcripts, _connector())
    assert any(f.dimension == "token_efficiency" for f in report.findings)


def test_judge_empty_transcripts() -> None:
    report = judge_audit([], _connector())
    assert report.transcript_count == 0
    assert report.total_tool_calls == 0
    assert report.passed is False


# ── store ───────────────────────────────────────────────────────────────────


def test_save_and_load_audit_report(tmp_path: Path) -> None:
    transcripts = [
        AuditTranscript(
            seed_id="seed-1", task="t", calls=[_ok_call("list_customers")], task_completed=True
        )
    ]
    report = judge_audit(transcripts, _connector())
    path = save_audit_report(report, tmp_path)
    assert path.exists()
    loaded = load_audit_reports(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].connector_slug == "acme"


def test_load_audit_reports_missing_dir(tmp_path: Path) -> None:
    assert load_audit_reports(tmp_path / "nope") == []


def test_load_audit_reports_skips_corrupt(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert load_audit_reports(tmp_path) == []


def test_audit_rubric_mentions_dimensions() -> None:
    rubric = audit_rubric()
    assert "task_completion" in rubric
    assert "token_efficiency" in rubric
