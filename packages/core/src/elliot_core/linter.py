"""Static analyser for ConnectorConfig agent-readiness."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from .danger_zone import DESTRUCTIVE_VERBS, HIGH_IMPACT_VERBS, name_tokens
from .sql import extract_sql_params, referenced_base_tables
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

# How long a tool description has to be, in two roles that are not the same
# number and should not pretend to be.
#
# _BLOCKING_DESCRIPTION_CHARS is the publish gate: below it there is no contract
# at all, DESCRIPTION_TOO_SHORT is an ERROR, and Elliot Cloud refuses the
# publish ("Connector has blocking lint issues").
#
# MIN_DESCRIPTION_CHARS is the graded bar — what elliot_core.eval.quality's
# min_length check asks for, "so an agent can tell what it does".
#
# They differ on purpose, but the SUGGESTION did not say so: it read "Write at
# least 15 characters", which is the gate, not the bar. Follow it exactly and
# the quality scan answers "Description too short (18 chars, min 20)" and takes
# 12.5 points — measured on "Lists the widgets.", which lints clean and grades
# at 87.5. An author fixing one check by doing what it told them should not be
# marked down by another for it, so the advice names the bar and the number
# lives in one place, the way _VERB_RE and _MUTATION_RE already do for the two
# questions these modules both ask.
MIN_DESCRIPTION_CHARS = 20
_BLOCKING_DESCRIPTION_CHARS = 15

# How long a PARAMETER description has to be to count as one. Unlike the tool
# description above this is a single number in both roles — the linter WARNs
# below it (PARAMETER_MISSING_DESCRIPTION) and the quality scan's
# has_params_described check asks for exactly the same thing — so it is defined
# once here and imported, rather than kept as a bare literal in one module and
# an "is it blank?" test in the other. They disagreed before: a parameter
# described as "id" linted as undescribed while the quality scan scored it
# clean, so a connector could be told to fix something its own score called
# fine.
MIN_PARAM_DESCRIPTION_CHARS = 5

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
# A READ tool whose NAME leads with an aggregation verb promises a *computed*
# answer (a count / total / summary), not the raw table. If its SQL carries no
# aggregate function or GROUP BY it returns raw rows instead — contradicting its
# own contract (principle 1) and spending the context budget the aggregation was
# meant to save (principle 2). Scoped to unambiguous aggregation verbs so a
# "list_totals" / "get_summary_page" (lead verb list/get) never trips it.
_AGGREGATION_VERBS = frozenset(
    {
        "count",
        "summarize",
        "summarise",
        "aggregate",
        "tally",
        "tabulate",
        "breakdown",
        "average",
        "avg",
    }
)
_AGGREGATE_SQL_RE = re.compile(r"\b(COUNT|SUM|AVG|MIN|MAX|GROUP\s+BY)\b")

_FILTER_PARAM_RE = re.compile(r"filter|search", re.IGNORECASE)
_FILTER_SEMANTICS_RE = re.compile(
    r"exact|substring|prefix|suffix|contains|case[- ]?insensitive|case[- ]?sensitive|"
    r"starts? with|ends? with|\bequals\b|wildcard|partial|matches|\blike\b",
    re.IGNORECASE,
)

# Canonical "description starts with an action verb" matcher. Accepts BOTH the
# imperative ("Return the X") and the third-person-singular present form
# ("Returns the X") — real authors and the agentic builder write both, and the
# trailing-`s` form is the more common professional style (it is exactly what
# this module's own WRITE_TOOL_DESCRIPTION suggestion recommends:
# "Creates...", "Deletes...", "Sends..."). Flagging it was a false positive
# that made the linter contradict both its own advice and the quality scan.
#
# This is the single source of truth for the verb check: elliot_core.eval.quality
# imports _VERB_RE from here so the linter and the quality scan can never drift
# apart on the same description.
# Canonical "the description names the mutation" matcher. WRITE_TOOL_DESCRIPTION
# below and elliot_core.eval.quality's mutation_hint ask the same question of
# the same string, and each used to carry its own word set — this module's was
# the shorter of the two, missing "submit" as well as every irreversible verb.
#
# HIGH_IMPACT_VERBS is part of it, and was the hole in it: the base names the
# ordinary mutations and none of the irreversible ones, so the tools the rule
# exists to protect an agent from were exactly the tools it could not
# recognise. Measured on a published connector whose ACTION tool reads "Cancels
# an order by id. Irreversible.": the stored lint report carried
# WRITE_TOOL_DESCRIPTION against it, and Elliot Cloud renders that report on
# the connector page — so the suggestion "add the mutation verb" was shown for
# a description that opens with one.
#
# Word-START matching, not substring. `ban` and `void` are short enough to
# misfire — "urban", "abandon" and "avoid" each contain one — while every
# inflection the substring test caught ("Cancels", "created", "unpublishes")
# still matches.
#
# Defined here, like _VERB_RE, so the linter and the quality scan can never
# drift apart on the same description again.
_MUTATION_WORDS = (
    frozenset({"write", "create", "update", "delete", "send", "insert", "remove", "submit"})
    | HIGH_IMPACT_VERBS
)
_MUTATION_RE = re.compile(r"\b(?:" + "|".join(sorted(_MUTATION_WORDS)) + r")", re.IGNORECASE)

_VERB_RE = re.compile(
    r"^\s*(return|list|get|find|create|update|delete|calculate|"
    # "browse" and "query" are two of the five _LIST_TOOL_PREFIXES above — the
    # leading tokens this module itself reads as "this tool returns a
    # collection", and holds to the list-tool pagination rule on that basis. The
    # other three (list, search, find) were verbs here; these two were not, so a
    # tool whose description opened with the very verb its id starts with was
    # told the description does not start with a verb. Measured on
    # browse_widgets / query_widgets with "Browses the widget records matching a
    # filter." and "Queries …": both drew DESCRIPTION_MISSING_VERB from the
    # linter and a starts_with_verb warning through analyze_tool_quality (87.5
    # against list_/search_/find_'s 100), while the identical sentence under the
    # other three prefixes passed clean. `query` is also one of the six
    # GENERIC_IDS, whose own check copy calls them "a generic verb (query,
    # fetch, run, …)" — fetch, run and execute all match here, and query alone
    # did not.
    #
    # `quer(?:y|ies)`, not a bare `query`, because the trailing `(?:es|s)?`
    # cannot spell the third person of a -y verb: "Queries" is not "query" plus
    # a suffix. Same reason `summari[sz]e` and `analy[sz]e` are written out.
    r"search|browse|quer(?:y|ies)|fetch|check|count|filter|retrieve|"
    r"aggregate|export|generate|compute|load|send|submit|"
    r"remove|show|run|execute|insert|stream|resolve|validate|"
    r"summari[sz]e|surface|pull|lookup|identify|detect|match|group|rank|sort|"
    r"join|map|report|yield|produce|build|compose|assemble|"
    # Mutation verbs — WRITE/ACTION tool descriptions naturally start with
    # these ("Add a note…", "Cancel an order…") and must not be told to
    # rewrite as "Return...".
    r"add|cancel|post|set|assign|mark|close|open|apply|attach|archive|"
    r"escalate|notify|publish|register|record|save|upload|trigger|start|stop|"
    r"grant|revoke|merge|move|rename|copy|sync|import|schedule|approve|"
    r"reject|complete|upsert|patch|modify|adjust|enable|disable|verify|"
    r"convert|extract|parse|analy[sz]e|describe|explain|preview|grade|audit|"
    # The rest of danger_zone.HIGH_IMPACT_VERBS. The block above was written
    # for exactly this and got one of them: "cancel" is here, and "refund",
    # "void", "suspend", "terminate", "deactivate" and the others are not — so
    # the most consequential actions a connector can expose were the ones told
    # their description does not start with an action verb. Measured through
    # analyze_tool_quality: "Refunds a payment to the original card.", "Voids
    # the invoice so it can never be paid." and "Suspends the user account
    # until an admin restores it." each drew a starts_with_verb warning, and
    # the linter's own verb rule reads off this same pattern, so the author was
    # told twice to rewrite copy that was already in the house style. Kept as
    # literals rather than interpolated from HIGH_IMPACT_VERBS because this
    # pattern is one readable regex and the two sets are conceptually distinct
    # — one asks "is this word an action verb", the other "does this id need a
    # destructive decision".
    r"refund|chargeback|payout|deactivate|suspend|terminate|void|ban|"
    r"deprovision|withdraw|unpublish|unsubscribe)"
    r"(?:es|s)?\b",
    re.IGNORECASE,
)


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


def _literal_url_password(url: str) -> bool:
    """True when ``url`` carries a literal password in its userinfo.

    A postgres/mysql source has no ``auth`` block at all — ``_resolve_dsn``
    reads the credential straight out of ``source.url``, either from a
    ``{{ env:VAR }}`` placeholder holding the whole DSN (what the shipped
    postgres-readonly template does) or, when the author pasted one, from a
    literal ``scheme://user:password@host/db``. Only the userinfo component is
    considered, so an ``@`` in a path or query — ``/users/a@b.com`` — is not
    mistaken for a credential, and a placeholder password is left alone.
    """
    if "://" not in url:
        return False
    try:
        password = urlsplit(url).password
    except ValueError:
        # Malformed authority (a bad port, say). Nothing to assert about it.
        return False
    if not password:
        return False
    # ``postgresql://app:{{ env:DB_PASSWORD }}@host/db`` — the credential is
    # already a reference, which is the shape this rule is asking for.
    return "{{" not in password


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
        for tbl in referenced_base_tables(tool.sql):
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


# A ``{{ skill.input.X }}`` binding inside a skill step's params.
_SKILL_INPUT_RE = re.compile(r"\{\{\s*skill\.input\.([A-Za-z0-9_]+)\s*\}\}")
# Every ``{{ ... }}`` template in a step param. The runtime resolves ONLY two
# forms — ``{{ skill.input.<name> }}`` and ``{{ steps.<alias>.<field> }}`` — so
# any other shape (a bare ``{{ x }}``, ``{{ inputs.x }}``, ``{{ a.rows[0].b }}``)
# fails at call time; the linter flags it here instead of at first run.
_SKILL_TEMPLATE_RE = re.compile(r"\{\{([^}]+)\}\}")


def _lint_skills(config: ConnectorConfig) -> list[LintIssue]:
    """Catch deterministic skills that can never run.

    A skill's ``steps`` chain is executed by the runtime, not the agent, so a
    step that targets a missing tool or leaves one of that tool's required
    parameters unbound fails only on first call — after lint and publish have
    passed. A skill that ships broken is the worst kind of "agent struggles",
    so these are ERRORs. Three ways a step chain is dead on arrival:

    * the target ``tool_id`` isn't a tool this connector defines;
    * a required tool parameter (``required`` and no ``default``) has no key in
      the step's ``params`` — nothing binds it, so the call is missing an arg;
    * a ``{{ skill.input.X }}`` binding names an input the skill never declares,
      so it resolves to nothing at runtime.

    Prose-only skills (no ``steps``) are left to the agent and skipped.
    """
    issues: list[LintIssue] = []
    tools_by_id = {t.id: t for t in config.tools}
    for skill in config.skills:
        input_names = {p.name for p in skill.input_parameters}
        # Aliases produced by EARLIER steps — a step can only reference an
        # earlier step's output, so this grows as we walk the chain.
        seen_aliases: set[str] = set()
        for step in skill.steps:
            target = tools_by_id.get(step.tool_id)
            if target is None:
                issues.append(
                    LintIssue(
                        severity="ERROR",
                        code="SKILL_STEP_UNKNOWN_TOOL",
                        tool_id=None,
                        message=(
                            f"Skill '{skill.id}' step '{step.alias}' calls tool "
                            f"'{step.tool_id}', which this connector does not define."
                        ),
                        suggestion="Point the step at an existing tool id, or add the tool.",
                    )
                )
                seen_aliases.add(step.alias)
                continue
            if not getattr(target, "enabled", True):
                issues.append(
                    LintIssue(
                        severity="ERROR",
                        code="SKILL_STEP_DISABLED_TOOL",
                        tool_id=target.id,
                        message=(
                            f"Skill '{skill.id}' step '{step.alias}' calls tool "
                            f"'{step.tool_id}', which is disabled. The runtime never "
                            "registers it, so the skill cannot run."
                        ),
                        suggestion=(
                            f"Re-enable '{step.tool_id}', point the step at a tool that is "
                            "enabled, or disable the skill too."
                        ),
                    )
                )
                seen_aliases.add(step.alias)
                continue
            required = [p.name for p in target.parameters if p.required and p.default is None]
            for name in required:
                if name not in step.params:
                    issues.append(
                        LintIssue(
                            severity="ERROR",
                            code="SKILL_STEP_MISSING_PARAM",
                            tool_id=target.id,
                            message=(
                                f"Skill '{skill.id}' step '{step.alias}' calls '{target.id}' "
                                f"without binding its required parameter '{name}' — the skill "
                                "fails at runtime with a missing argument."
                            ),
                            suggestion=(
                                f"Bind '{name}' in the step params: a literal value, or a "
                                f"reference like {{{{ skill.input.{name} }}}} / "
                                "{{ steps.<alias>.<field> }}."
                            ),
                        )
                    )
            for key, value in step.params.items():
                if not isinstance(value, str):
                    continue
                for ref in _SKILL_INPUT_RE.findall(value):
                    if ref not in input_names:
                        issues.append(
                            LintIssue(
                                severity="ERROR",
                                code="SKILL_STEP_DANGLING_INPUT",
                                tool_id=target.id,
                                message=(
                                    f"Skill '{skill.id}' step '{step.alias}' binds '{key}' to "
                                    f"skill input '{ref}', which the skill does not declare — it "
                                    "resolves to nothing at runtime."
                                ),
                                suggestion=(
                                    f"Add '{ref}' to the skill's input_parameters, or correct "
                                    "the binding name."
                                ),
                            )
                        )
                # Every {{ ... }} template must be one of the two forms the
                # runtime resolves; anything else fails at call time.
                for expr in _SKILL_TEMPLATE_RE.findall(value):
                    parts = expr.strip().split(".")
                    is_input = len(parts) >= 3 and parts[0] == "skill" and parts[1] == "input"
                    is_step = len(parts) >= 3 and parts[0] == "steps"
                    if not is_input and not is_step:
                        issues.append(
                            LintIssue(
                                severity="ERROR",
                                code="SKILL_STEP_BAD_BINDING",
                                tool_id=target.id,
                                message=(
                                    f"Skill '{skill.id}' step '{step.alias}' binds '{key}' with "
                                    f"'{{{{ {expr.strip()} }}}}', which the runtime cannot resolve "
                                    "— it fails at runtime with SKILL_TEMPLATE_UNRESOLVED."
                                ),
                                suggestion=(
                                    "Use '{{ skill.input.<name> }}' for a skill input or "
                                    "'{{ steps.<alias>.<field> }}' for an earlier step's "
                                    "first-row field."
                                ),
                            )
                        )
                    elif is_step and parts[1] not in seen_aliases:
                        issues.append(
                            LintIssue(
                                severity="ERROR",
                                code="SKILL_STEP_DANGLING_STEP",
                                tool_id=target.id,
                                message=(
                                    f"Skill '{skill.id}' step '{step.alias}' references "
                                    f"'{{{{ steps.{parts[1]}.{'.'.join(parts[2:])} }}}}', but no "
                                    f"earlier step is aliased '{parts[1]}' — it resolves to "
                                    "nothing at runtime."
                                ),
                                suggestion=(
                                    "Reference an alias produced by an EARLIER step (a step "
                                    "cannot use its own or a later step's output)."
                                ),
                            )
                        )
            seen_aliases.add(step.alias)
    return issues


# Tokens that mark a tool id/name as leftover scaffolding rather than a real,
# agent-facing contract. Agents select tools by name, so a "get_stuff_now" or a
# "probe"/"tmp" tool that shipped by accident poisons tool selection and wastes
# context. Deliberately conservative (WARN, whole-token match) to avoid firing
# on legitimate names.
_SCAFFOLD_TOKENS = frozenset(
    {
        "stuff",
        "foo",
        "bar",
        "baz",
        "qux",
        "probe",
        "tmp",
        "temp",
        "placeholder",
        "todo",
        "wip",
        "asdf",
        "xxx",
        "untitled",
        "dummy",
        "scratch",
    }
)
_SCAFFOLD_DESC_RE = re.compile(r"^\s*(probe|debug|todo|fixme)\b\s*[:\-]", re.IGNORECASE)


def _lint_scaffold_names(config: ConnectorConfig) -> list[LintIssue]:
    """Flag tools that read as leftover build scaffolding, not a shipped contract.

    An agent picks tools by their id/name, so a placeholder like ``get_stuff_now``
    or a debug ``echo_search_probe`` that survives into a published connector
    degrades tool selection and spends context on noise. WARN, not ERROR: the
    author may have a reason, but nearly always it's cruft to rename or drop.
    """
    issues: list[LintIssue] = []
    for tool in config.tools:
        tokens = set(re.split(r"[^a-z0-9]+", tool.id.lower()))
        tokens |= set(re.split(r"[^a-z0-9]+", (tool.name or "").lower()))
        hit = tokens & _SCAFFOLD_TOKENS
        if hit:
            issues.append(
                LintIssue(
                    severity="WARN",
                    code="TOOL_NAME_SCAFFOLD",
                    tool_id=tool.id,
                    message=(
                        f"Tool '{tool.id}' looks like leftover scaffolding (token "
                        f"'{sorted(hit)[0]}'). Agents select tools by name, so a placeholder "
                        "id poisons tool selection."
                    ),
                    suggestion=(
                        "Rename it to a descriptive, verb-first id that says what it returns "
                        "or does — or remove it if it was a build-time probe."
                    ),
                )
            )
        elif _SCAFFOLD_DESC_RE.match(tool.description or ""):
            issues.append(
                LintIssue(
                    severity="WARN",
                    code="TOOL_DESC_SCAFFOLD",
                    tool_id=tool.id,
                    message=(
                        f"Tool '{tool.id}' description reads like a debug/probe note, not an "
                        "agent-facing contract."
                    ),
                    suggestion=(
                        "Describe what the tool does for an agent, or remove the tool if it "
                        "was scaffolding."
                    ),
                )
            )
    return issues


# Placeholders in a path template, e.g. ``/users/{user_id}`` -> ``user_id``.
_PATH_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _forwarded_param_names(tool: object) -> set[str]:
    """Param names a tool forwards verbatim to the upstream API.

    For a REST passthrough (``rest_query_params``) or a WRITE/ACTION tool
    (``api_mapping`` query/body/path params), the parameter name MUST equal the
    upstream API's spelling — ``q`` and ``key`` are CKAN's and BoI's real param
    names. Renaming them to satisfy a generic/too-short lint rule silently
    breaks the forwarded call, so these names are exempt from those two rules.
    """
    names: set[str] = set()
    names.update(getattr(tool, "rest_query_params", None) or [])
    mapping = getattr(tool, "api_mapping", None)
    if mapping is not None:
        names.update(getattr(mapping, "query_params", None) or [])
        names.update(getattr(mapping, "body_params", None) or [])
        template = getattr(mapping, "path_template", None)
        if template:
            names.update(_PATH_PLACEHOLDER_RE.findall(template))
    return names


def _starts_with_verb(description: str) -> bool:
    return bool(_VERB_RE.match(description))


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

    # Disabled tools are never registered, so they are not part of the contract
    # the connector offers — grade what agents can actually call. The full set
    # is kept for _lint_skills, which has to see a disabled tool to catch a
    # skill step pointing at one (dead on arrival, same class as F4).
    declared = config
    served_tools = [t for t in config.tools if getattr(t, "enabled", True)]
    if len(served_tools) != len(config.tools):
        config = config.model_copy(update={"tools": served_tools})

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

    # ── skill executability (a deterministic skill that can never run) ────────
    # Deliberately the full set: a step calling a disabled tool must be caught.
    issues.extend(_lint_skills(declared))

    # ── scaffold/placeholder tool names left in a shipped connector ───────────
    issues.extend(_lint_scaffold_names(config))

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

        if len(desc.strip()) < _BLOCKING_DESCRIPTION_CHARS:
            issues.append(
                LintIssue(
                    severity="ERROR",
                    code="DESCRIPTION_TOO_SHORT",
                    tool_id=tool.id,
                    message=f"Tool '{tool.id}' description is too short ({len(desc)} chars).",
                    suggestion=(
                        f"Write at least {MIN_DESCRIPTION_CHARS} characters starting with a "
                        'verb: "Return all...", "Get a single..."'
                    ),
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

        # A tool that NAMES itself an aggregation must actually aggregate.
        lead_token = next(iter(re.split(r"[^a-z0-9]+", tool.id.lower())), "")
        if (
            lead_token in _AGGREGATION_VERBS
            and tool.sql
            and not _AGGREGATE_SQL_RE.search(sql_upper)
        ):
            issues.append(
                LintIssue(
                    severity="WARN",
                    code="AGGREGATION_NAME_NO_AGGREGATE",
                    tool_id=tool.id,
                    message=(
                        f"Tool '{tool.id}' is named like an aggregation ('{lead_token}…') but its "
                        "SQL has no COUNT/SUM/AVG/GROUP BY — it returns raw rows, not the computed "
                        "answer the name promises."
                    ),
                    suggestion=(
                        "Compute the result in SQL (COUNT/SUM/AVG with GROUP BY) so the tool returns "
                        "a small answer, or rename it to a list/get tool if it really returns rows."
                    ),
                )
            )

        # Names forwarded verbatim to the upstream API must keep the API's
        # spelling — exempt them from the descriptive-name rules below.
        forwarded = _forwarded_param_names(tool)

        # A parameter an agent can pass but the tool never consumes is a broken
        # contract: the agent fills it in expecting a filter/effect and gets
        # none, so a "customers on the pro plan" request silently returns every
        # customer. Only a raw-SQL tool is checked (its params must appear as
        # ``:name``); a param routed to the API (forwarded) or bound by a
        # structured filter_groups is consumed elsewhere and never flagged.
        if tool.sql and not tool.filter_groups:
            consumed = set(extract_sql_params(tool.sql)) | forwarded
            for param in tool.parameters:
                if param.name not in consumed:
                    issues.append(
                        LintIssue(
                            severity="WARN",
                            code="PARAMETER_UNUSED",
                            tool_id=tool.id,
                            message=(
                                f"Tool '{tool.id}' declares parameter '{param.name}' but its SQL "
                                "never binds it — an agent that passes it gets no effect, so the "
                                "result is silently unfiltered."
                            ),
                            suggestion=(
                                f"Reference it in the SQL (e.g. `WHERE (:{param.name} IS NULL OR "
                                f"col = :{param.name})`), or remove the parameter."
                            ),
                        )
                    )

        for param in tool.parameters:
            if len(param.name) <= 2 and param.name not in forwarded:
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
            if len(param_desc.strip()) < MIN_PARAM_DESCRIPTION_CHARS:
                issues.append(
                    LintIssue(
                        severity="WARN",
                        code="PARAMETER_MISSING_DESCRIPTION",
                        tool_id=tool.id,
                        message=(
                            f"Tool '{tool.id}' parameter '{param.name}' is not described "
                            f"({len(param_desc.strip())} chars)."
                        ),
                        suggestion=(
                            f"Add a description of at least {MIN_PARAM_DESCRIPTION_CHARS} "
                            "characters so agents know what value to pass."
                        ),
                    )
                )

            if (
                len(param.name) > 2
                and param.name.lower() in _GENERIC_PARAM_NAMES
                and param.name not in forwarded
            ):
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
            if not _MUTATION_RE.search(desc):
                issues.append(
                    LintIssue(
                        severity="INFO",
                        code="WRITE_TOOL_DESCRIPTION",
                        tool_id=tool.id,
                        message=f"Tool '{tool.id}' is category {tool.category} but description doesn't mention mutation.",
                        suggestion='Add the mutation verb ("Creates...", "Deletes...", "Sends...") so agents don\'t call it accidentally.',
                    )
                )

            # A high-impact action the destructive-verb heuristic doesn't
            # auto-detect (cancel/refund/suspend/payout…), left unclassified, is
            # treated by the runtime as safe to auto-run — so an agent operates
            # the danger zone with no confirmation round-trip. Only nudge when
            # the author hasn't decided (destructive is None) and no
            # already-auto-detected verb (delete/…) is present to flag it anyway.
            if tool.destructive is None:
                tokens = name_tokens(tool.id)
                high_impact = tokens & HIGH_IMPACT_VERBS
                if high_impact and tokens.isdisjoint(DESTRUCTIVE_VERBS):
                    verb = sorted(high_impact)[0]
                    issues.append(
                        LintIssue(
                            severity="WARN",
                            code="DESTRUCTIVE_NOT_FLAGGED",
                            tool_id=tool.id,
                            message=(
                                f"Tool '{tool.id}' looks irreversible ('{verb}…') but isn't "
                                "marked as the danger zone, so agents auto-run it without "
                                "confirmation."
                            ),
                            suggestion=(
                                "Set `destructive: true` so clients confirm before calling it, "
                                "or `destructive: false` if it is genuinely safe to auto-run."
                            ),
                        )
                    )

    for source in config.sources:
        url = source.url or ""
        auth_key = source.auth.secret_key if source.auth else ""
        if auth_key and auth_key in url:
            issues.append(
                LintIssue(
                    severity="ERROR",
                    code="SECRET_IN_URL",
                    tool_id=None,
                    message=f"Source '{source.id}' may have a secret embedded in the URL.",
                    suggestion="Use auth.secret_key to reference an env var; never put secrets in URLs.",
                )
            )
        # The same rule for the sources that carry their credential in the URL
        # and nowhere else. The check above can only fire when the secret is
        # ALSO declared in auth.secret_key — and a postgres/mysql source has no
        # auth block, so a DSN with the password in it never reached this rule
        # at all, despite being the single most common way a credential ends up
        # in a connector file. _lint_source_auth's own contract is "a published
        # connector must ship NO literal secrets", the code's published meaning
        # is "a secret is embedded in source.url", and the shipped
        # postgres-readonly template already models the fix — but nothing
        # enforced any of it: measured, `postgresql://app:s3cr3t@db:5432/orders`
        # linted clean while the REST equivalent raised AUTH_LITERAL_SECRET.
        #
        # It stays quiet after publish too, which is why lint is the place to
        # catch it: check_secrets() scans for {{ env:… }}, so a literal DSN
        # declares no required secrets and the pre-publish panel gives an
        # all-clear, and the dashboard's Sources card prints source.url
        # verbatim — password included — as its location line.
        elif _literal_url_password(url):
            issues.append(
                LintIssue(
                    severity="ERROR",
                    code="SECRET_IN_URL",
                    tool_id=None,
                    message=(
                        f"Source '{source.id}' has a password embedded in its connection URL."
                    ),
                    suggestion=(
                        "Store the whole connection string as a secret and set url to "
                        "{{ env:DATABASE_URL }}; never ship a literal credential in the "
                        "connector file."
                    ),
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
            # A SQL-only haystack missed the non-SQL tool shapes entirely:
            # WRITE/ACTION tools move fields through ``api_mapping`` (query/body
            # params, path template), and READ passthrough tools forward
            # ``rest_query_params`` straight to the upstream. A sensitive field
            # there is exposed just as much as one in a SELECT — scan them too.
            haystack += " " + " ".join(tool.rest_query_params)
            if tool.api_mapping is not None:
                haystack += " " + " ".join(tool.api_mapping.query_params)
                haystack += " " + " ".join(tool.api_mapping.body_params)
                if tool.api_mapping.path_template:
                    haystack += " " + tool.api_mapping.path_template
            if field_re.search(haystack):
                issues.append(
                    LintIssue(
                        severity="ERROR",
                        code="SENSITIVE_FIELD_EXPOSED",
                        tool_id=tool.id,
                        message=(
                            f"Tool '{tool.id}' appears to expose the sensitive "
                            f"field '{field}' (in its SQL, output, or forwarded "
                            f"query/body params), which the product intent marked "
                            "as never-expose."
                        ),
                        suggestion=f"Drop '{field}' from this tool's output and request, or redact it.",
                    )
                )

    return issues
