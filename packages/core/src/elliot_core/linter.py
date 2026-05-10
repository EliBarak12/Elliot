"""Static analyser for ConnectorConfig agent-readiness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .types import ConnectorConfig

Severity = Literal["ERROR", "WARN", "INFO"]

_VERBS = {
    "return",
    "get",
    "list",
    "fetch",
    "find",
    "search",
    "count",
    "create",
    "update",
    "delete",
    "send",
    "run",
    "execute",
    "check",
    "calculate",
    "summarise",
    "summarize",
    "filter",
    "retrieve",
    "show",
}


@dataclass
class LintIssue:
    severity: Severity
    code: str
    tool_id: str | None
    message: str
    suggestion: str


def _starts_with_verb(description: str) -> bool:
    first_word = description.strip().split()[0].lower().rstrip(".,:")
    return first_word in _VERBS


def lint_connector(config: ConnectorConfig) -> list[LintIssue]:
    issues: list[LintIssue] = []

    for tool in config.tools:
        desc = tool.description or ""

        if len(desc.strip()) < 15:
            issues.append(
                LintIssue(
                    severity="ERROR",
                    code="DESCRIPTION_TOO_SHORT",
                    tool_id=tool.id,
                    message=f"Tool '{tool.id}' description is too short ({len(desc)} chars).",
                    suggestion='Write at least 15 characters starting with a verb: "Return all...", "Get a single..."',
                )
            )
        elif not _starts_with_verb(desc):
            issues.append(
                LintIssue(
                    severity="WARN",
                    code="DESCRIPTION_MISSING_VERB",
                    tool_id=tool.id,
                    message=f"Tool '{tool.id}' description should start with a verb.",
                    suggestion='Rewrite as "Return...", "Get...", "List...", "Create...", "Count..."',
                )
            )

        sql_upper = (tool.sql or "").upper()
        if "SELECT *" in sql_upper and "LIMIT" not in sql_upper and "WHERE" not in sql_upper:
            issues.append(
                LintIssue(
                    severity="ERROR",
                    code="UNBOUNDED_SELECT",
                    tool_id=tool.id,
                    message=f"Tool '{tool.id}' uses SELECT * with no WHERE or LIMIT.",
                    suggestion="Add LIMIT 50 or add a required/optional filter parameter.",
                )
            )
        elif "SELECT *" in sql_upper and "LIMIT" not in sql_upper:
            issues.append(
                LintIssue(
                    severity="WARN",
                    code="SELECT_STAR_NO_LIMIT",
                    tool_id=tool.id,
                    message=f"Tool '{tool.id}' uses SELECT * without a LIMIT.",
                    suggestion="Add LIMIT :limit with a default, or select only the columns agents need.",
                )
            )

        for param in tool.parameters:
            if len(param.name) <= 2:
                issues.append(
                    LintIssue(
                        severity="WARN",
                        code="PARAMETER_NAME_TOO_SHORT",
                        tool_id=tool.id,
                        message=f"Tool '{tool.id}' has a parameter named '{param.name}' which is ambiguous.",
                        suggestion=f"Rename '{param.name}' to something descriptive like 'user_id' or 'status_filter'.",
                    )
                )
            param_desc = param.description or ""
            if len(param_desc.strip()) < 5:
                issues.append(
                    LintIssue(
                        severity="WARN",
                        code="PARAMETER_MISSING_DESCRIPTION",
                        tool_id=tool.id,
                        message=f"Tool '{tool.id}' parameter '{param.name}' has no description.",
                        suggestion="Add a description so agents know what value to pass.",
                    )
                )

        if tool.category in ("WRITE", "ACTION"):
            mutation_words = {"write", "create", "update", "delete", "send", "insert", "remove"}
            if not any(w in desc.lower() for w in mutation_words):
                issues.append(
                    LintIssue(
                        severity="INFO",
                        code="WRITE_TOOL_DESCRIPTION",
                        tool_id=tool.id,
                        message=f"Tool '{tool.id}' is category {tool.category} but description doesn't mention mutation.",
                        suggestion='Add the mutation verb ("Creates...", "Deletes...", "Sends...") so agents don\'t call it accidentally.',
                    )
                )

    for source in config.sources:
        if source.auth and source.auth.secret_key and source.auth.secret_key in (source.url or ""):
            issues.append(
                LintIssue(
                    severity="ERROR",
                    code="SECRET_IN_URL",
                    tool_id=None,
                    message=f"Source '{source.id}' may have a secret embedded in the URL.",
                    suggestion="Use auth.secret_key to reference an env var; never put secrets in URLs.",
                )
            )

    return issues
