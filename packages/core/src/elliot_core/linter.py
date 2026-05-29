"""Static analyser for ConnectorConfig agent-readiness."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .sql import extract_table_names
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

# A string parameter whose name implies filtering/searching, where the agent
# must know the match semantics (exact vs substring vs prefix, case handling)
# to use it correctly. Without it, agents guess wrong — e.g. asking for "cities
# starting with L" against an exact-match field silently returns nothing.
_FILTER_PARAM_RE = re.compile(r"filter|search", re.IGNORECASE)
_FILTER_SEMANTICS_RE = re.compile(
    r"exact|substring|prefix|suffix|contains|case[- ]?insensitive|case[- ]?sensitive|"
    r"starts? with|ends? with|\bequals\b|wildcard|partial|matches|\blike\b",
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


def _is_env_placeholder(value: str) -> bool:
    return value.startswith("{{ env:") and value.endswith(" }}")


def _is_bare_env_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", value))


def _lint_source_auth(config: ConnectorConfig) -> list[LintIssue]:
    """Validate auth blocks so per-user / distributable connectors are safe.

    A published connector must ship NO literal secrets, declare an oauth2 block
    when it uses OAuth, and treat the per-user secret_key as a vault slot rather
    than an env-resolved value.
    """
    issues: list[LintIssue] = []
    for source in config.sources:
        auth = source.auth
        if auth is None:
            continue
        where = f"source '{source.id}'"

        if auth.type == "oauth2" and auth.oauth2 is None:
            issues.append(
                LintIssue(
                    severity="ERROR",
                    code="AUTH_OAUTH2_MISSING_CONFIG",
                    tool_id=None,
                    message=f"{where} uses type 'oauth2' but has no 'oauth2' config block.",
                    suggestion="Add oauth2 with authorization_url, token_url, scopes and {{ env }} client creds.",
                )
            )

        if auth.oauth2 is not None:
            for field_name in ("client_id_secret", "client_secret_secret"):
                val = getattr(auth.oauth2, field_name)
                if not _is_env_placeholder(val) and not _is_bare_env_name(val):
                    issues.append(
                        LintIssue(
                            severity="WARN",
                            code="AUTH_OAUTH2_CLIENT_NOT_ENV",
                            tool_id=None,
                            message=f"{where} oauth2.{field_name} is a literal value, not an env reference.",
                            suggestion="Use {{ env:VAR }} so the OAuth app secret is never shipped in the connector.",
                        )
                    )

        if auth.scope == "per_user":
            if auth.type == "oauth2" and _is_env_placeholder(auth.secret_key):
                issues.append(
                    LintIssue(
                        severity="WARN",
                        code="AUTH_PER_USER_SLOT_IS_ENV",
                        tool_id=None,
                        message=f"{where} is per_user oauth2 but secret_key is an env placeholder.",
                        suggestion="For per_user auth, secret_key is a vault slot name (e.g. 'access_token'), not {{ env }}.",
                    )
                )
        elif not _is_env_placeholder(auth.secret_key) and not _is_bare_env_name(auth.secret_key):
            issues.append(
                LintIssue(
                    severity="WARN",
                    code="AUTH_LITERAL_SECRET",
                    tool_id=None,
                    message=f"{where} secret_key looks like a hardcoded secret.",
                    suggestion="Use {{ env:VAR }} so the connector file ships no secrets.",
                )
            )
    return issues


def _lint_tool_source_coverage(config: ConnectorConfig) -> list[LintIssue]:
    """Catch tools whose SQL references a source that the runtime won't load.

    At call time the runtime materializes ONLY the tables belonging to a tool's
    ``source_ids``. If the tool's SQL references a base table that maps to a
    source NOT in ``source_ids`` (e.g. the SQL was edited to point at a
    different source but ``source_ids`` wasn't re-inferred), the runtime fails
    with "no such table" / returns 0 rows — while every other static check
    passes. This rule makes that decoupling visible before publish.

    A referenced identifier that matches no known source (CTE aliases like
    ``ds``, or genuinely external names) is ignored — only references that
    DO resolve to a connector source but are missing from ``source_ids`` are
    flagged. Longest key wins so ``catalog_a`` beats ``catalog``.
    """
    # Candidate table-name keys for each source -> the source identifier that
    # source_ids would contain (source.id; after build that equals the name).
    key_to_sid: list[tuple[str, str]] = []
    for src in config.sources:
        for key in {src.table_name, src.name, src.id}:
            if key:
                key_to_sid.append((key, src.id))

    issues: list[LintIssue] = []
    for tool in config.tools:
        if not tool.sql:
            continue
        tool_sources = set(tool.source_ids or [])
        reported: set[str] = set()
        for tbl in extract_table_names(tool.sql):
            owner: str | None = None
            best_len = -1
            for key, sid in key_to_sid:
                if (tbl == key or tbl.startswith(key + "_")) and len(key) > best_len:
                    best_len, owner = len(key), sid
            if owner is None or owner in tool_sources or owner in reported:
                continue
            reported.add(owner)
            issues.append(
                LintIssue(
                    severity="ERROR",
                    code="TOOL_SOURCE_NOT_LOADED",
                    tool_id=tool.id,
                    message=(
                        f"Tool '{tool.id}' SQL references table '{tbl}' from source "
                        f"'{owner}', but that source is not in the tool's source_ids — "
                        "the runtime won't materialize it, so the call fails with "
                        "'no such table' / 0 rows even though preview works."
                    ),
                    suggestion=(
                        "Re-create the tool, or re-run elliot_update_tool with the SQL so "
                        "source_ids is re-inferred from the tables the SQL references."
                    ),
                )
            )
    return issues


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

    # ── source auth checks (per-user / OAuth distribution safety) ────────────
    issues.extend(_lint_source_auth(config))

    # ── SQL ↔ source_ids coverage (runtime "no such table" guard) ────────────
    issues.extend(_lint_tool_source_coverage(config))

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
        # Word-boundary matching: a plain substring check treats a column named
        # RATE_LIMIT or WHERE_CLAUSE as a real LIMIT / WHERE clause and
        # suppresses the warning.
        has_limit = bool(re.search(r"\bLIMIT\b", sql_upper))
        has_where = bool(re.search(r"\bWHERE\b", sql_upper))
        has_select_star = bool(re.search(r"\bSELECT\s+\*", sql_upper))
        if has_select_star and not has_limit and not has_where:
            issues.append(
                LintIssue(
                    severity="ERROR",
                    code="UNBOUNDED_SELECT",
                    tool_id=tool.id,
                    message=f"Tool '{tool.id}' uses SELECT * with no WHERE or LIMIT.",
                    suggestion="Add LIMIT 50 or add a required/optional filter parameter.",
                )
            )
        elif has_select_star and not has_limit:
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

            # Only warn when there's already a (non-trivial) description but it
            # omits the match semantics — the empty-description case is covered
            # by PARAMETER_MISSING_DESCRIPTION above.
            if (
                param.type == "string"
                and _FILTER_PARAM_RE.search(param.name)
                and len(param_desc.strip()) >= 5
                and not _FILTER_SEMANTICS_RE.search(param_desc)
            ):
                issues.append(
                    LintIssue(
                        severity="WARN",
                        code="FILTER_SEMANTICS_UNCLEAR",
                        tool_id=tool.id,
                        message=(
                            f"Tool '{tool.id}' parameter '{param.name}' looks like a filter "
                            "but its description doesn't state the match semantics."
                        ),
                        suggestion=(
                            f"Put it in '{param.name}'s OWN description (not the tool "
                            "description): say whether matching is exact, substring/contains, "
                            "prefix, or case-insensitive so agents query it correctly."
                        ),
                    )
                )

        if (
            tool.category == "READ"
            and tool.sql
            and _is_list_tool(tool.id)
            and not re.search(r"\bLIMIT\b", (tool.sql or "").upper())
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
