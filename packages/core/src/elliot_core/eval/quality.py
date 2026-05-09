from __future__ import annotations

import re
from dataclasses import dataclass, field

from elliot_core.types.connector import ConnectorConfig
from elliot_core.types.tool import ToolDefinition

_VERB_RE = re.compile(
    r"^(Returns|Lists|Gets|Finds|Creates|Updates|Deletes|Calculates|"
    r"Searches|Fetches|Checks|Counts|Filters|Retrieves)\b",
    re.IGNORECASE,
)
_JARGON = frozenset(
    {"sql", "endpoint", "query", "table", "column", "database", "api", "select", "from", "where"}
)
_GENERIC_IDS = frozenset({"query", "get_data", "fetch", "run", "execute", "call"})
_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass
class ToolIssue:
    check: str
    severity: str  # "error" | "warning"
    message: str


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

    if len(tool.description.strip()) < 20:
        issues.append(
            ToolIssue(
                "min_length",
                "error",
                f"Description too short ({len(tool.description)} chars, min 20)",
            )
        )

    if not _VERB_RE.match(tool.description):
        issues.append(
            ToolIssue(
                "starts_with_verb",
                "warning",
                "Description should start with a verb (Returns, Lists, Gets, Finds, ...)",
            )
        )

    words = frozenset(tool.description.lower().split())
    found = words & _JARGON
    if found:
        issues.append(
            ToolIssue(
                "no_jargon",
                "warning",
                f"Description contains technical jargon: {', '.join(sorted(found))}",
            )
        )

    for p in tool.parameters:
        if not (p.description or "").strip():
            issues.append(
                ToolIssue(
                    "has_params_described",
                    "error",
                    f"Parameter '{p.name}' has no description",
                )
            )

    if not _SNAKE_RE.fullmatch(tool.id):
        issues.append(
            ToolIssue(
                "name_snake_case",
                "error",
                f"Tool id '{tool.id}' is not snake_case",
            )
        )

    if tool.id in _GENERIC_IDS:
        issues.append(
            ToolIssue(
                "no_generic_names",
                "warning",
                f"Tool id '{tool.id}' is too generic — use a domain-specific name",
            )
        )

    total = 5 + len(tool.parameters)
    score = max(0.0, (1 - len(issues) / total) * 100) if total else 100.0
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
