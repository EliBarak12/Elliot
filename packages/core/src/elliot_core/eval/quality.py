from __future__ import annotations

import re
from dataclasses import dataclass, field

from elliot_core.danger_zone import HIGH_IMPACT_VERBS, name_tokens
from elliot_core.linter import (
    _ENUM_DESC_RE,
    _MUTATION_RE,
    _PAGINATION_HINTS,
    _VERB_RE,
    MIN_DESCRIPTION_CHARS,
    MIN_PARAM_DESCRIPTION_CHARS,
    _is_list_tool,
)
from elliot_core.types.connector import ConnectorConfig
from elliot_core.types.tool import ToolDefinition

# The "starts with an action verb" matcher (_VERB_RE), the closed-value-set
# matcher (_ENUM_DESC_RE), the pagination-parameter set (_PAGINATION_HINTS) and
# the list-tool detector (_is_list_tool) are all defined once in
# elliot_core.linter and imported here so the linter and the quality scan can
# never disagree about the same connector. "from" was removed from the jargon
# set: it is an ordinary English preposition ("Return rows from the orders
# source") far more often than SQL leakage, so flagging it produced false
# positives on otherwise clean, natural descriptions.
_JARGON = frozenset({"sql", "endpoint", "table", "column", "database", "api", "select"})
_WORD_RE = re.compile(r"[a-z]+")
_GENERIC_IDS = frozenset({"query", "get_data", "fetch", "run", "execute", "call"})
_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# ── MCP-builder best-practice principles ────────────────────────────────────
# Every quality check is tagged with the principle from Anthropic's "mcp-builder"
# skill (https://github.com/anthropics/skills/blob/main/skills/mcp-builder/SKILL.md)
# that it enforces. Tagging lets the Evaluation page show, per connector, how
# well a tool set follows the published MCP server guidance — grouped by
# principle — instead of just a bare score. The OSS Studio and Elliot Cloud
# Evaluation pages render BEST_PRACTICES verbatim, so it is the single source of
# truth for what "agent-ready" means across both products.
PRINCIPLE_NAMING = "naming"
PRINCIPLE_CONTEXT = "context"
PRINCIPLE_SCHEMA = "schema"
PRINCIPLE_ANNOTATIONS = "annotations"
PRINCIPLE_CONSISTENCY = "consistency"

BEST_PRACTICES: list[dict[str, str]] = [
    {
        "id": PRINCIPLE_NAMING,
        "title": "Tool naming & discoverability",
        "summary": (
            "Clear, action-oriented, domain-specific names and verb-first "
            "descriptions so agents locate the right tool quickly."
        ),
    },
    {
        "id": PRINCIPLE_CONTEXT,
        "title": "Context management",
        "summary": (
            "Concise, jargon-free descriptions and bounded results — list tools "
            "support a LIMIT or pagination so they never dump an unbounded set."
        ),
    },
    {
        "id": PRINCIPLE_SCHEMA,
        "title": "Input & output schema design",
        "summary": (
            "Every parameter carries a description, and closed value sets are "
            "typed as enums so agents cannot guess wrong."
        ),
    },
    {
        "id": PRINCIPLE_ANNOTATIONS,
        "title": "Tool annotations",
        "summary": (
            "Mutating (WRITE / ACTION) tools state their effect in the "
            "description so agents never call them by accident."
        ),
    },
    {
        "id": PRINCIPLE_CONSISTENCY,
        "title": "Consistency",
        "summary": "Uniform snake_case identifiers across the whole tool set.",
    },
]


@dataclass
class ToolIssue:
    check: str
    severity: str  # "error" | "warning"
    message: str
    # The mcp-builder principle this check enforces (see BEST_PRACTICES). Lets
    # the Evaluation page group issues by best-practice area.
    principle: str = PRINCIPLE_NAMING


@dataclass
class ToolQualityScore:
    tool_id: str
    score: float  # 0–100
    issues: list[ToolIssue] = field(default_factory=list)


@dataclass
class ConnectorQualityScore:
    overall_score: float  # 0–100
    tool_scores: list[ToolQualityScore] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0


def analyze_tool_quality(tool: ToolDefinition) -> ToolQualityScore:
    issues: list[ToolIssue] = []
    # Count the checks that actually apply to this tool so the score is the
    # fraction of *applicable* best-practice checks that pass. A check is only
    # counted when it is evaluated (e.g. the enum check only applies to open
    # string parameters), so adding conditional checks never penalizes a tool
    # the check doesn't apply to.
    applicable = 0

    # context: concise but sufficient description
    applicable += 1
    if len(tool.description.strip()) < MIN_DESCRIPTION_CHARS:
        issues.append(
            ToolIssue(
                "min_length",
                "error",
                f"Description too short ({len(tool.description)} chars, "
                f"min {MIN_DESCRIPTION_CHARS})",
                PRINCIPLE_CONTEXT,
            )
        )

    # naming: action-oriented, verb-first description
    applicable += 1
    if not _VERB_RE.match(tool.description):
        issues.append(
            ToolIssue(
                "starts_with_verb",
                "warning",
                "Description should start with a verb (Returns, Lists, Gets, Finds, ...)",
                PRINCIPLE_NAMING,
            )
        )

    # context: no implementation jargon leaking to the agent
    applicable += 1
    # Tokenised on word characters, not whitespace. `.split()` leaves the
    # punctuation attached, so "table." and "table," are not "table" — and a
    # description names its noun last far more often than mid-sentence, which
    # made the common shape of this defect the one shape that slipped through.
    # Measured before the change: "Returns rows from the orders table.",
    # "Returns the customer records from the API.", "Returns everything stored
    # in the database.", "Runs the statement against the endpoint." and
    # "Returns rows using SQL." were all clean, and the two descriptions that
    # did trip it were flagged only on their mid-sentence word — "Returns data
    # from the SQL endpoint." reported `sql` and let `endpoint.` past.
    words = frozenset(_WORD_RE.findall(tool.description.lower()))
    found = words & _JARGON
    if found:
        issues.append(
            ToolIssue(
                "no_jargon",
                "warning",
                f"Description contains technical jargon: {', '.join(sorted(found))}",
                PRINCIPLE_CONTEXT,
            )
        )

    # schema: every parameter described. The bar is the linter's
    # MIN_PARAM_DESCRIPTION_CHARS, not "is it blank?" — a one-word placeholder
    # tells an agent nothing, and grading it clean while the linter WARNs on it
    # makes the two graders contradict each other on the same connector.
    for p in tool.parameters:
        applicable += 1
        param_desc = (p.description or "").strip()
        if len(param_desc) < MIN_PARAM_DESCRIPTION_CHARS:
            issues.append(
                ToolIssue(
                    "has_params_described",
                    "error",
                    f"Parameter '{p.name}' is not described "
                    f"({len(param_desc)} chars, min {MIN_PARAM_DESCRIPTION_CHARS})",
                    PRINCIPLE_SCHEMA,
                )
            )

    # schema: closed value sets typed as enums (only applies to open strings)
    for p in tool.parameters:
        if p.type == "string" and not p.enum:
            applicable += 1
            if _ENUM_DESC_RE.search(p.description or ""):
                issues.append(
                    ToolIssue(
                        "enum_for_closed_set",
                        "warning",
                        (
                            f"Parameter '{p.name}' describes a fixed value set but is an "
                            "open string — declare the allowed values as an enum"
                        ),
                        PRINCIPLE_SCHEMA,
                    )
                )

    # consistency: snake_case identifier
    applicable += 1
    if not _SNAKE_RE.fullmatch(tool.id):
        issues.append(
            ToolIssue(
                "name_snake_case",
                "error",
                f"Tool id '{tool.id}' is not snake_case",
                PRINCIPLE_CONSISTENCY,
            )
        )

    # naming: not a generic catch-all id
    applicable += 1
    if tool.id in _GENERIC_IDS:
        issues.append(
            ToolIssue(
                "no_generic_names",
                "warning",
                f"Tool id '{tool.id}' is too generic — use a domain-specific name",
                PRINCIPLE_NAMING,
            )
        )

    # context: raw-SQL list tools must bound their result. Full-fetch READ tools
    # are already capped by ToolDefinition.limit; raw SQL bypasses that, so it
    # needs an explicit LIMIT or a pagination parameter (mirrors the linter's
    # MISSING_PAGINATION rule).
    if tool.category == "READ" and tool.sql and _is_list_tool(tool.id):
        applicable += 1
        has_limit = bool(re.search(r"\bLIMIT\b", tool.sql.upper()))
        has_page = any(p.name.lower() in _PAGINATION_HINTS for p in tool.parameters)
        if not has_limit and not has_page:
            issues.append(
                ToolIssue(
                    "pagination",
                    "warning",
                    (
                        "List-style tool has no LIMIT and no pagination parameter — "
                        "it can return an unbounded result"
                    ),
                    PRINCIPLE_CONTEXT,
                )
            )

    # annotations: mutating tools must state the mutation in their description
    if tool.category in ("WRITE", "ACTION"):
        applicable += 1
        if not _MUTATION_RE.search(tool.description):
            issues.append(
                ToolIssue(
                    "mutation_hint",
                    "warning",
                    (
                        f"{tool.category} tool's description doesn't mention the mutation "
                        "— agents may call it by accident"
                    ),
                    PRINCIPLE_ANNOTATIONS,
                )
            )

        # annotations: a high-impact action (cancel/refund/suspend…) the author
        # left unclassified is auto-run by the runtime with no confirmation.
        # Mirrors the linter's DESTRUCTIVE_NOT_FLAGGED so the quality SCORE — not
        # just the linter's issue list — reflects danger-zone hygiene. Applies
        # only to high-impact-verb tools; an explicit destructive flag passes it.
        if name_tokens(tool.id) & HIGH_IMPACT_VERBS:
            applicable += 1
            if tool.destructive is None:
                issues.append(
                    ToolIssue(
                        "danger_zone_classified",
                        "warning",
                        (
                            f"'{tool.id}' is a high-impact action but isn't classified — set "
                            "destructive: true to gate it behind confirmation, or false if safe"
                        ),
                        PRINCIPLE_ANNOTATIONS,
                    )
                )

    total = applicable or 1
    score = max(0.0, (1 - len(issues) / total) * 100)
    return ToolQualityScore(tool_id=tool.id, score=round(score, 1), issues=issues)


def analyze_connector_quality(config: ConnectorConfig) -> ConnectorQualityScore:
    tool_scores = [analyze_tool_quality(t) for t in config.tools]
    all_issues = [i for ts in tool_scores for i in ts.issues]
    return ConnectorQualityScore(
        overall_score=(
            round(sum(ts.score for ts in tool_scores) / len(tool_scores), 1)
            if tool_scores
            else 100.0
        ),
        tool_scores=tool_scores,
        error_count=sum(1 for i in all_issues if i.severity == "error"),
        warning_count=sum(1 for i in all_issues if i.severity == "warning"),
    )
