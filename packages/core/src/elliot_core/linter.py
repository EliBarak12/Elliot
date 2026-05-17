"""Static analyser for ConnectorConfig agent-readiness."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .types import ConnectorConfig

Severity = Literal["ERROR", "WARN", "INFO"]

# Connector-level: more tools is not better — it inflates token cost on every
# agent call and makes tool selection harder (Anthropic, "Writing effective
# tools for AI agents").
_MAX_TOOLS = 25

# Parameter names that are technically valid but tell an agent nothing about
# what value to pass. The existing PARAMETER_NAME_TOO_SHORT rule catches the
# <=2 char cases; this catches the longer-but-still-generic ones.
_GENERIC_PARAM_NAMES = frozenset(
    {
        "data",
        "value",
        "input",
        "query",
        "arg",
        "args",
        "obj",
        "object",
        "item",
        "type",
        "key",
        "val",
        "param",
        "params",
        "name",
    }
)

# Parameter names that mean "the result is bounded" — a list/search tool that
# has none of these and no SQL LIMIT can dump an unbounded result at an agent.
_PAGINATION_HINTS = frozenset(
    {
        "limit",
        "offset",
        "page",
        "per_page",
        "page_size",
        "cursor",
        "max_results",
        "top",
    }
)

# Tool-id leading tokens that imply a potentially large collection result.
_LIST_TOOL_PREFIXES = ("list", "search", "find", "query", "browse")

# A free-text string parameter whose description reads like a closed value set
# should be a typed enum instead.
_ENUM_DESC_RE = re.compile(
    r"\bone of\b|\bvalid values?\b|\bmust be\b|\beither\b.+\bor\b",
    re.IGNORECASE,
)

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
    "aggregate",
    "export",
    "generate",
    "compute",
    "load",
    "submit",
    "remove",
    "insert",
    "stream",
    "resolve",
    "validate",
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


def _is_list_tool(tool_id: str) -> bool:
    first = tool_id.split("_", 1)[0].lower()
    return first in _LIST_TOOL_PREFIXES


def lint_connector(
    config: ConnectorConfig,
    sensitive_fields: list[str] | None = None,
) -> list[LintIssue]:
    """Statically analyse ``config`` for agent-readiness.

    ``sensitive_fields`` — when supplied (typically from the captured
    ``ProductIntent``) — flags any tool that returns one of those fields.
    """
    issues: list[LintIssue] = []

    # ── connector-level checks ──────────────────────────────────────────────
    if len(config.tools) > _MAX_TOOLS:
        issues.append(
            LintIssue(
                severity="WARN",
                code="TOO_MANY_TOOLS",
                tool_id=None,
                message=(
                    f"Connector exposes {len(config.tools)} tools "
                    f"(> {_MAX_TOOLS}). Large tool sets raise token cost on "
                    "every call and make tool selection harder."
                ),
                suggestion="Keep the 5-15 tools agents actually need; drop or merge the rest.",
            )
        )

    seen_ids: set[str] = set()
    for tool in config.tools:
        if tool.id in seen_ids:
            issues.append(
                LintIssue(
                    severity="ERROR",
                    code="DUPLICATE_TOOL_ID",
                    tool_id=tool.id,
                    message=f"Tool id '{tool.id}' is defined more than once.",
                    suggestion="Every tool needs a unique, descriptive id.",
                )
            )
        seen_ids.add(tool.id)

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

            if len(param.name) > 2 and param.name.lower() in _GENERIC_PARAM_NAMES:
                issues.append(
                    LintIssue(
                        severity="WARN",
                        code="PARAMETER_NAME_GENERIC",
                        tool_id=tool.id,
                        message=(
                            f"Tool '{tool.id}' parameter '{param.name}' is generic — "
                            "agents cannot tell what value it wants."
                        ),
                        suggestion=(
                            f"Rename '{param.name}' to be specific: 'customer_id', "
                            "'search_text', 'order_status', ..."
                        ),
                    )
                )

            if param.type == "string" and not param.enum and _ENUM_DESC_RE.search(param_desc):
                issues.append(
                    LintIssue(
                        severity="WARN",
                        code="PARAMETER_SHOULD_BE_ENUM",
                        tool_id=tool.id,
                        message=(
                            f"Tool '{tool.id}' parameter '{param.name}' describes a "
                            "fixed value set but is an open string."
                        ),
                        suggestion="Declare the allowed values as an `enum` so agents can't guess wrong.",
                    )
                )

        if (
            tool.category == "READ"
            and tool.sql
            and _is_list_tool(tool.id)
            and "LIMIT" not in (tool.sql or "").upper()
            and not any(p.name.lower() in _PAGINATION_HINTS for p in tool.parameters)
        ):
            issues.append(
                LintIssue(
                    severity="WARN",
                    code="MISSING_PAGINATION",
                    tool_id=tool.id,
                    message=(
                        f"List-style tool '{tool.id}' has no LIMIT and no "
                        "pagination parameter — it can return an unbounded result."
                    ),
                    suggestion="Add `LIMIT :limit` with a default, or a limit/offset/cursor parameter.",
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

    for field in sensitive_fields or []:
        if not field.strip():
            continue
        field_re = re.compile(rf"\b{re.escape(field)}\b", re.IGNORECASE)
        for tool in config.tools:
            haystack = tool.sql or ""
            haystack += " " + " ".join(rf.field for rf in tool.return_fields)
            if tool.output_schema:
                haystack += " " + " ".join(str(k) for k in tool.output_schema)
            if field_re.search(haystack):
                issues.append(
                    LintIssue(
                        severity="ERROR",
                        code="SENSITIVE_FIELD_EXPOSED",
                        tool_id=tool.id,
                        message=(
                            f"Tool '{tool.id}' appears to return the sensitive "
                            f"field '{field}', which the product intent marked "
                            "as never-expose."
                        ),
                        suggestion=f"Drop '{field}' from this tool's output, or redact it.",
                    )
                )

    return issues
