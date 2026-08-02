"""Tool definition management — create, update, delete tools in the registry."""

from __future__ import annotations

import re
from typing import Annotated, Any

import structlog
from pydantic import Field

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.mcp_compat import FastMCP
from elliot_core.naming import is_valid_identifier, slugify_identifier
from elliot_core.sql import extract_sql_params, has_select_star, referenced_base_tables
from elliot_core.sqlite.query_runner import validate_tool_sql
from elliot_core.tokens import estimate_tokens
from elliot_core.tools.param_validation import validate_call_params
from elliot_core.types.tool import ToolDefinition
from elliot_mcp_plugin.session import ElliotSession

# A preview result costing more than this is worth flagging — it is the token
# bill an agent pays every time it calls the tool (the runtime's large-result
# threshold). Kept here so the build-time preview and the runtime trace speak
# about "token-heavy" with the same number.
_HEAVY_PREVIEW_TOKENS = 500

# JSON-schema description of a single tool parameter spec, advertised on the
# array params so an agent sees the expected item shape instead of a bare
# "object". Runtime stays a permissive list[dict]; this is schema guidance only.
_PARAM_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "type": {
            "type": "string",
            "enum": ["string", "integer", "number", "boolean", "date"],
        },
        "required": {"type": "boolean"},
        "description": {"type": "string"},
        "enum": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name"],
}
_ParamList = Annotated[list[dict[str, Any]], Field(json_schema_extra={"items": _PARAM_ITEM_SCHEMA})]
_Category = Annotated[str, Field(json_schema_extra={"enum": ["READ", "WRITE", "ACTION"]})]

log = structlog.get_logger(__name__)

# Map friendly category names to valid ToolDefinition Literals
_CATEGORY_MAP: dict[str, str] = {
    "read": "READ",
    "write": "WRITE",
    "action": "ACTION",
    "aggregate": "READ",
}


def preview_tool(
    session: ElliotSession,
    tool_id: str,
    supplied: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a tool's SQL against the session's SQLite engine and return rows.

    Shared between the OSS ``elliot_preview_tool`` MCP wrapper and the Cloud
    ``POST /api/me/workspace/tools/{id}/preview`` endpoint. Raises
    ``ElliotError`` for missing tool, missing SQL, or missing required
    parameters — callers convert to their transport's error shape.
    """
    tool = session.registry.get(tool_id)
    if tool is None:
        raise ElliotError("NOT_FOUND", f"Tool not found: {tool_id}")
    sql = session.tool_sql.get(tool_id)
    if not sql:
        # A pure REST passthrough tool carries no SQL — it can only be previewed
        # by fetching live (see elliot_preview_tool, which routes those through
        # preview_tool_live). Point the caller there instead of a bare
        # "no SQL" dead end (audit H8).
        if tool.rest_query_params:
            raise ElliotError(
                "PASSTHROUGH_PREVIEW",
                f"Tool '{tool_id}' is a REST passthrough tool — preview it live via "
                "elliot_preview_tool (it fetches the source on each call).",
            )
        # A WRITE/ACTION mutation tool has nothing safe to preview: executing
        # it would fire a real request at the upstream API. Say that instead
        # of a misleading "no SQL" error.
        if tool.api_mapping is not None:
            raise ElliotError(
                "ACTION_PREVIEW_UNAVAILABLE",
                f"Tool '{tool_id}' is a {tool.category} mutation tool — preview would "
                "execute a real request against the upstream API, so it is not run "
                "at design time. Point the source at a staging endpoint to test it, "
                "or verify after publish.",
            )
        raise ElliotError("NOT_FOUND", f"No SQL defined for tool: {tool_id}")

    supplied = dict(supplied or {})

    missing = [p.name for p in tool.parameters if p.required and supplied.get(p.name) in (None, "")]
    if missing:
        raise ElliotError(
            "VALIDATION_REQUIRED",
            f"Missing required parameter(s) for tool '{tool_id}': {', '.join(missing)}",
            detail={"tool_id": tool_id, "missing": missing},
        )

    # Enforce the same unknown-param / enum / numeric-bound / type rules the
    # published runtime uses, so preview and production agree (audit H5/H6).
    # Empty strings are treated as "not supplied" to match the binding below.
    validate_call_params(tool, {k: v for k, v in supplied.items() if v not in (None, "")})

    bound: dict[str, object] = {}
    for p in tool.parameters:
        if p.name in supplied and supplied[p.name] not in (None, ""):
            bound[p.name] = supplied[p.name]
        elif p.default is not None:
            bound[p.name] = p.default
        else:
            bound[p.name] = None

    rows = session.engine.query(sql, bound)
    # The token cost is the signature metric — show it at the moment the author
    # inspects the tool, counted the same way the runtime trace and dashboard
    # will, so a token-heavy tool is caught before publish, not after agents pay.
    tokens = estimate_tokens(rows)
    out: dict[str, Any] = {"rows": rows, "row_count": len(rows), "estimated_tokens": tokens}
    if tokens > _HEAVY_PREVIEW_TOKENS:
        out["note"] = (
            f"This result is ~{tokens} tokens — an agent pays that on every call. Project only "
            "the columns the agent needs and add a LIMIT so it fits a context window (principle 2)."
        )
    return out


# Preview rows are a sanity check, not a data export — cap the live passthrough
# response so a chatty endpoint can't flood the agent's context.
_PASSTHROUGH_PREVIEW_ROWS = 50


async def preview_tool_live(
    session: ElliotSession,
    tool_id: str,
    supplied: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Preview a tool, fetching live for REST passthrough tools (audit H8).

    SQL-backed tools run against the session SQLite snapshot exactly as
    :func:`preview_tool` does. A pure passthrough tool (no SQL, forwards
    ``rest_query_params``) is fetched live from its REST source with the
    supplied params so it can be exercised in-session before publish — closing
    the gap where ``create_rest_tool`` succeeded but the tool could never be
    tested.
    """
    tool = session.registry.get(tool_id)
    if tool is None:
        raise ElliotError("NOT_FOUND", f"Tool not found: {tool_id}")
    if not session.tool_sql.get(tool_id) and tool.rest_query_params:
        return await _preview_passthrough(session, tool, dict(supplied or {}))
    return preview_tool(session, tool_id, supplied)


async def _preview_passthrough(
    session: ElliotSession,
    tool: ToolDefinition,
    supplied: dict[str, Any],
) -> dict[str, Any]:
    from elliot_core.sources.api_fetcher import fetch_endpoint

    if not tool.source_ids:
        raise ElliotError("NOT_FOUND", f"Passthrough tool '{tool.id}' has no bound source.")
    source = session.sources.get(tool.source_ids[0])
    if source is None:
        raise ElliotError(
            "NOT_FOUND", f"Source not found for tool '{tool.id}': {tool.source_ids[0]}"
        )
    if source.type != "rest":
        raise ElliotError(
            "VALIDATION_ERROR",
            f"Passthrough tool '{tool.id}' is bound to a '{source.type}' source, not REST.",
        )

    missing = [p.name for p in tool.parameters if p.required and supplied.get(p.name) in (None, "")]
    if missing:
        raise ElliotError(
            "VALIDATION_REQUIRED",
            f"Missing required parameter(s) for tool '{tool.id}': {', '.join(missing)}",
            detail={"tool_id": tool.id, "missing": missing},
        )
    validated = validate_call_params(
        tool, {k: v for k, v in supplied.items() if v not in (None, "")}
    )

    api_params = {k: validated[k] for k in tool.rest_query_params if k in validated}
    secrets = session.workspace.load_secrets()
    result = await fetch_endpoint(source, secrets, extra_params=api_params)
    rows = list(result.rows)[:_PASSTHROUGH_PREVIEW_ROWS]
    log.info("tool.preview.passthrough", tool_id=tool.id, source_id=source.id, rows=len(rows))
    out: dict[str, Any] = {
        "rows": rows,
        "row_count": len(rows),
        # The token cost of the returned slice — the signature metric, counted
        # the same way the runtime trace will. A heavy slice means each live call
        # is expensive; tighten the upstream page size or the fields returned.
        "estimated_tokens": estimate_tokens(rows),
        "mode": "rest_passthrough",
        "live": True,
        "total_fetched": len(result.rows),
    }
    warnings = getattr(result, "warnings", None)
    if warnings:
        out["warnings"] = list(warnings)
    return out


def _normalize_tool_input(tool: dict[str, Any]) -> dict[str, Any]:
    """Accept the same loose shape that elliot_create_tool accepts.

    `elliot_create_tool` derives `id` from `name` and lower-cases the category,
    but `elliot_validate_tool` historically required the strict ToolDefinition
    shape (snake-case id, uppercase category). Apply the same normalizations
    here so an agent can hand the same payload to either tool.
    """
    out = dict(tool)
    if not out.get("id") and out.get("name"):
        out["id"] = slugify_identifier(str(out["name"]))
    category = out.get("category")
    if isinstance(category, str):
        mapped = _CATEGORY_MAP.get(category.lower())
        if mapped is not None:
            out["category"] = mapped
    return out


def _tool_sql_warnings(sql: str) -> list[str]:
    """Non-blocking authoring smells in a tool's SQL (audit B2)."""
    warnings: list[str] = []
    if has_select_star(sql):
        warnings.append(
            "SQL uses 'SELECT *' — name the specific columns the agent needs so the "
            "tool returns a typed, context-sized result (principle 2)."
        )
    return warnings


def _reject_undeclared_params(sql: str, parameters: list[dict[str, Any]]) -> None:
    """Raise if the SQL binds a ``:param`` that isn't declared (audit B2).

    SQLite would otherwise accept the tool at create time and fail every call
    with a cryptic "no such parameter" — a broken tool shipped to other agents.
    """
    declared = {str(p["name"]) for p in (parameters or []) if isinstance(p, dict) and p.get("name")}
    undeclared = [n for n in extract_sql_params(sql) if n not in declared]
    if undeclared:
        raise ElliotError(
            "UNDECLARED_PARAM",
            f"SQL references undeclared parameter(s): {', '.join(undeclared)}. "
            "Declare each one in `parameters` (or remove the ':' reference).",
            detail={"undeclared": undeclared, "declared": sorted(declared)},
        )


def _infer_source_ids_from_sql(sql: str, session: ElliotSession) -> list[str]:
    """Pick the minimum set of session sources a tool's SQL actually needs.

    Auto-assigning every source to every tool caused two real problems:
    (1) a bearer-auth failure on one source broke unrelated tool calls
    because the runtime materializes every ``source_id`` before executing;
    and (2) it wastes outbound HTTP calls on each invocation.

    Mapping: walk the SQL, pull each table identifier referenced after
    ``FROM`` / ``JOIN``, and match it against the registered sources by
    name. Flattener-produced child tables (``orders_line_items``) get
    bucketed under their parent (``orders``) by a prefix match — they're
    materialized as part of the parent source. When the SQL references no
    known source (or the parse missed everything), fall back to "all
    sources" so the tool isn't silently broken.
    """
    # ``referenced_base_tables`` strips CTE aliases so a WITH-clause tool
    # doesn't try to bind a query-local alias (``x``) to a source.
    referenced = referenced_base_tables(sql)
    if not referenced:
        return list(session.sources.keys())

    source_by_name = {src.name: sid for sid, src in session.sources.items()}
    matched: list[str] = []
    for tbl in referenced:
        if tbl in source_by_name:
            sid = source_by_name[tbl]
            if sid not in matched:
                matched.append(sid)
            continue
        # Try prefix match for flattener child tables: "orders_line_items"
        # depends on the "orders" source. Longest prefix wins to avoid
        # matching "orders" to "organizations" by accident.
        candidates = sorted(
            (n for n in source_by_name if tbl.startswith(n + "_")),
            key=len,
            reverse=True,
        )
        if candidates:
            sid = source_by_name[candidates[0]]
            if sid not in matched:
                matched.append(sid)

    return matched or list(session.sources.keys())


def register_tool_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_create_tool(
        name: str,
        description: str,
        category: _Category,
        sql: str,
        parameters: _ParamList,
    ) -> dict:  # type: ignore[type-arg]
        """Define a new SQL-backed business tool and register it in the session.

        SQL conventions (the runtime executes against in-memory SQLite):
          * Reference tool parameters with a colon prefix — ``WHERE plan = :plan`` —
            and declare each in ``parameters``. ``{{ plan }}`` / Jinja syntax is
            REJECTED at registration time.
          * Tables are named after the ``name`` you passed to
            ``elliot_discover_source`` (quote with double quotes:
            ``FROM "users"``).
          * Flattener child tables are ``{source}_{field}`` — e.g. nested
            arrays in ``orders.line_items[]`` produce ``orders_line_items``.
          * Every materialized table carries an auto-injected ``_id``
            (sequential within the table). Child tables additionally carry
            ``_parent_id`` (the parent row's ``_id``) and ``_index`` (the
            child's position in the parent array). JOIN child to parent on
            ``child._parent_id = parent._id`` — this is the only reliable
            link when the upstream JSON has no natural foreign key.

        ``source_ids`` is inferred from the SQL — only the source whose
        tables appear after ``FROM`` / ``JOIN`` will be materialized at
        call time, so unrelated source failures don't cascade.
        """
        try:
            if category.lower() not in _CATEGORY_MAP:
                valid = ", ".join(sorted(_CATEGORY_MAP))
                return {"error": f"Unknown category '{category}'. Valid: {valid}"}
            mapped_category = _CATEGORY_MAP[category.lower()]
            # Derive a snake_case id from the free-text name. Passing the name
            # through verbatim let ids contain spaces/colons, which then blew up
            # downstream as a cryptic "[Errno 22] Invalid argument" on Windows
            # (the id is used in a filename) and failed the linter's snake_case
            # rule. Slugify + validate up front instead.
            tool_id = slugify_identifier(name)
            if not is_valid_identifier(tool_id):
                raise ElliotError(
                    "INVALID_TOOL_NAME",
                    f"Could not derive a valid tool id from name {name!r}. Use a name "
                    "containing at least one letter (letters, numbers, spaces and "
                    "underscores are allowed).",
                )
            # Reject non-read-only SQL before it is stored and later executed
            # against the in-memory mirror. The runtime's DB push-down path
            # validates too, but the SQLite path executed tool.sql directly.
            sql_ok, sql_reason = validate_tool_sql(sql)
            if not sql_ok:
                raise ElliotError("INVALID_SQL", sql_reason)
            # B2: an undeclared ``:param`` would register fine and fail only at
            # call time with a cryptic SQLite error — reject it at create time.
            _reject_undeclared_params(sql, parameters)
            source_ids = _infer_source_ids_from_sql(sql, session)
            tool = ToolDefinition.model_validate(
                {
                    "id": tool_id,
                    "name": name,
                    "description": description,
                    "category": mapped_category,
                    "source_ids": source_ids,
                    "parameters": parameters,
                }
            )
            session.registry.add(tool)
            session.tool_sql[tool.id] = sql
            session.save()
            log.info("tool.created", tool_id=tool.id)
            result: dict[str, Any] = {"tool_id": tool.id, "status": "created"}
            # SELECT * is a soft smell, not a hard error: legitimate on a small
            # curated table, but a star projection bloats context and lets the
            # output schema drift. Flag it so the author can tighten the
            # contract (principle 2) without blocking creation.
            warnings = _tool_sql_warnings(sql)
            if warnings:
                result["warnings"] = warnings
            return result
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("tool.create.failed", error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_create_rest_tool(
        name: str,
        description: str,
        source_id: str,
        query_params: _ParamList,
        parameters: _ParamList | None = None,
    ) -> dict:  # type: ignore[type-arg]
        """Define a LIVE REST passthrough tool (call-time parameterized fetch).

        Unlike elliot_create_tool — which queries data snapshotted from a fixed
        URL at build time — a passthrough tool forwards its ``query_params`` to a
        REST source as URL query parameters on EVERY call and returns the live
        response. Use it for large or server-side-filtered APIs where a fixed
        snapshot won't work — e.g. a datastore/search endpoint that needs a
        resource id per call:

            GET <source url>?resource_id=<resource_id>&q=<q>

        Args:
            source_id: id of a REST source (from elliot_discover_source) whose
                URL is the base endpoint; query_params are appended to it per
                call.
            query_params: the parameters forwarded as query params. Each is
                {"name": str, "type"?: "string|integer|number|boolean|date",
                "required"?: bool, "description"?: str, "enum"?: [str]}. They
                become the tool's agent-facing inputs AND its rest_query_params.
            parameters: optional extra declared parameters that are NOT
                forwarded (rare — e.g. a value used only by an optional SQL
                post-filter).
        """
        try:
            source = session.sources.get(source_id)
            if source is None:
                return {
                    "error": (
                        f"Source not found: {source_id}. Discover a REST source first with "
                        "elliot_discover_source."
                    )
                }
            if source.type != "rest":
                return {
                    "error": (
                        f"Source '{source_id}' is type '{source.type}', not 'rest'. Passthrough "
                        "tools require a REST source."
                    )
                }
            if not query_params:
                return {"error": "query_params must list at least one parameter to forward."}

            tool_id = slugify_identifier(name)
            if not is_valid_identifier(tool_id):
                raise ElliotError(
                    "INVALID_TOOL_NAME",
                    f"Could not derive a valid tool id from name {name!r}.",
                )

            def _norm(p: dict[str, Any]) -> dict[str, Any]:
                pname = p.get("name")
                if not pname:
                    raise ElliotError("VALIDATION_ERROR", "each query_param needs a 'name'.")
                return {
                    "name": pname,
                    "type": p.get("type", "string"),
                    "required": p.get("required", True),
                    "description": p.get("description", ""),
                    "enum": p.get("enum"),
                }

            qp = [_norm(p) for p in query_params]
            all_params = qp + [_norm(p) for p in (parameters or [])]
            tool = ToolDefinition.model_validate(
                {
                    "id": tool_id,
                    "name": name,
                    "description": description,
                    "category": "READ",
                    "source_ids": [source_id],
                    "rest_query_params": [p["name"] for p in qp],
                    "parameters": all_params,
                }
            )
            session.registry.add(tool)
            # Pure passthrough tools carry no SQL; drop any stale entry.
            session.tool_sql.pop(tool.id, None)
            session.save()
            log.info("tool.created.rest_passthrough", tool_id=tool.id, source_id=source_id)
            return {"tool_id": tool.id, "status": "created", "mode": "rest_passthrough"}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("tool.create_rest.failed", error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_create_action_tool(
        name: str,
        description: str,
        source_id: str,
        method: str,
        parameters: _ParamList,
        path_template: str = "",
        query_params: list[str] | None = None,
        body_params: list[str] | None = None,
        body_format: str = "json",
        category: str = "ACTION",
        destructive: bool | None = None,
    ) -> dict:  # type: ignore[type-arg]
        """Define a WRITE/ACTION tool — a real HTTP mutation against a REST source.

        This is how a connector lets agents ACT on the product (create an
        order, update a ticket, cancel a job) instead of only reading from it.
        On every call the runtime sends ``method`` to the source's URL +
        ``path_template``, routing the declared parameters into the request:

            <source url> + path_template   e.g. "/orders/{order_id}/cancel"

        Args:
            source_id: id of a REST source (from elliot_discover_source; use
                skip_probe=true for endpoints that only answer to mutations).
            method: "POST" | "PUT" | "PATCH" | "DELETE". For GET reads use
                elliot_create_tool / elliot_create_rest_tool instead.
            parameters: EVERY agent-facing input, same shape as
                elliot_create_tool ({"name", "type", "required",
                "description", "enum"}). Describe each one — the description
                is the agent's contract.
            path_template: optional path appended to the source URL; ``{param}``
                placeholders are filled (URL-encoded) from same-named
                parameters.
            query_params: parameter names sent as URL query string values.
            body_params: parameter names sent in the request body ("json" or
                "form" per body_format). The source's static ``body`` fields
                ride along and per-call values override them.
            category: "ACTION" (default) or "WRITE" — pick WRITE for plain data
                mutations and ACTION for operations with side effects beyond
                data.
            destructive: the "danger zone" override. Leave unset and the runtime
                infers it from the verb (delete/remove/… → gated). Set true to
                mark a business-critical action the verbs miss (execute_refund,
                cancel_subscription, send_payout) as destructive so clients gate
                it behind human approval; set false to clear a false positive.

        Every parameter must be routed somewhere (path placeholder, query, or
        body) — unrouted parameters are rejected so the tool cannot silently
        drop an agent's input.
        """
        try:
            source = session.sources.get(source_id)
            if source is None:
                return {
                    "error": (
                        f"Source not found: {source_id}. Discover a REST source first with "
                        "elliot_discover_source (skip_probe=true for mutation-only endpoints)."
                    )
                }
            if source.type != "rest":
                return {
                    "error": (
                        f"Source '{source_id}' is type '{source.type}', not 'rest'. "
                        "WRITE/ACTION tools mutate a REST API."
                    )
                }
            mapped_category = _CATEGORY_MAP.get(category.lower())
            if mapped_category not in ("WRITE", "ACTION"):
                return {"error": f"category must be WRITE or ACTION, got {category!r}."}
            normalized_method = method.strip().upper()
            if normalized_method not in ("POST", "PUT", "PATCH", "DELETE"):
                return {
                    "error": (
                        f"method must be POST, PUT, PATCH or DELETE, got {method!r}. "
                        "For reads use elliot_create_tool or elliot_create_rest_tool."
                    )
                }

            tool_id = slugify_identifier(name)
            if not is_valid_identifier(tool_id):
                raise ElliotError(
                    "INVALID_TOOL_NAME",
                    f"Could not derive a valid tool id from name {name!r}.",
                )

            declared = {
                str(p["name"]) for p in (parameters or []) if isinstance(p, dict) and p.get("name")
            }
            if not declared:
                return {"error": "parameters must declare at least one agent-facing input."}
            placeholders = set(re.findall(r"\{([a-zA-Z0-9_]+)\}", path_template or ""))
            query_names = list(query_params or [])
            body_names = list(body_params or [])
            undeclared = sorted((placeholders | set(query_names) | set(body_names)) - declared)
            if undeclared:
                raise ElliotError(
                    "UNDECLARED_PARAM",
                    "path_template/query_params/body_params reference undeclared "
                    f"parameter(s): {', '.join(undeclared)}. Declare each in `parameters`.",
                    detail={"undeclared": undeclared, "declared": sorted(declared)},
                )
            unrouted = sorted(declared - placeholders - set(query_names) - set(body_names))
            if unrouted:
                raise ElliotError(
                    "UNROUTED_PARAM",
                    f"Parameter(s) {', '.join(unrouted)} are declared but not routed to the "
                    "path, query_params, or body_params — the runtime would silently drop "
                    "them. Route each one (or remove it).",
                    detail={"unrouted": unrouted},
                )

            tool = ToolDefinition.model_validate(
                {
                    "id": tool_id,
                    "name": name,
                    "description": description,
                    "category": mapped_category,
                    "source_ids": [source_id],
                    "parameters": parameters,
                    "api_mapping": {
                        "method": normalized_method,
                        "path_template": path_template or None,
                        "query_params": query_names,
                        "body_params": body_names,
                        "body_format": body_format,
                    },
                    "destructive": destructive,
                }
            )
            session.registry.add(tool)
            # Mutation tools carry no SQL; drop any stale entry under this id.
            session.tool_sql.pop(tool.id, None)
            session.save()
            log.info(
                "tool.created.action",
                tool_id=tool.id,
                source_id=source_id,
                method=normalized_method,
            )
            return {
                "tool_id": tool.id,
                "status": "created",
                "mode": "api_mutation",
                "note": (
                    "Mutation tools are not executed by preview or the publish smoke "
                    "test — verify against a staging endpoint or after publish. Agents "
                    "see it flagged destructive."
                ),
            }
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("tool.create_action.failed", error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_update_tool(tool_id: str, patch: dict) -> dict:  # type: ignore[type-arg]
        """Partially update a tool definition (name, description, sql, parameters)."""
        try:
            tool = session.registry.get(tool_id)
            if tool is None:
                return {"error": f"Tool not found: {tool_id}"}
            sql_patch = patch.pop("sql", None)
            if sql_patch is not None:
                sql_ok, sql_reason = validate_tool_sql(sql_patch)
                if not sql_ok:
                    raise ElliotError("INVALID_SQL", sql_reason)
                # Re-run the B2 create-time guards against the new SQL. Use the
                # patched parameters when the same patch redefines them,
                # otherwise the tool's current parameters.
                effective_params = patch.get("parameters")
                if effective_params is None:
                    effective_params = [p.model_dump() for p in tool.parameters]
                _reject_undeclared_params(sql_patch, effective_params)
                session.tool_sql[tool_id] = sql_patch
                # SQL changed → the tables it references (and therefore the
                # sources the runtime must materialize) may have changed too.
                # elliot_create_tool infers source_ids from the SQL; update
                # MUST do the same, otherwise the tool keeps stale source_ids
                # and its SQL silently decouples from the materialized schema
                # ("no such table" / 0 rows at runtime while lint stays green).
                patch["source_ids"] = _infer_source_ids_from_sql(sql_patch, session)
            if patch:
                session.registry.update(tool_id, patch)
            session.save()
            return {"tool_id": tool_id, "status": "updated"}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_list_tools() -> dict:  # type: ignore[type-arg]
        """List all user-defined connector tools with their full definitions."""
        try:
            # Pick up any tools the agent created since our last list — even
            # if the agent's MCP client spawned its own plugin process and
            # writes to the same workspace.
            session.refresh_from_disk()
            # SQL lives in session.tool_sql, not on the model (see
            # elliot_create_tool), so merge it in just like elliot_get_tool —
            # otherwise the Studio editor renders an empty query field.
            tools = []
            for t in session.registry.get_all():
                dumped = t.model_dump()
                if dumped.get("sql") is None:
                    dumped["sql"] = session.tool_sql.get(t.id)
                tools.append(dumped)
            return {
                "tools": tools,
                "count": len(tools),
            }
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_get_tool(tool_id: str) -> dict:  # type: ignore[type-arg]
        """Return the full definition of a tool including its SQL."""
        try:
            tool = session.registry.get(tool_id)
            if tool is None:
                return {"error": f"Tool not found: {tool_id}"}
            result = tool.model_dump()
            result["sql"] = session.tool_sql.get(tool_id)
            return result
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_delete_tool(tool_id: str) -> dict:  # type: ignore[type-arg]
        """Remove a tool from the session registry."""
        try:
            if session.registry.get(tool_id) is None:
                return {"error": f"Tool not found: {tool_id}"}
            session.registry.delete(tool_id)
            session.tool_sql.pop(tool_id, None)
            session.save()
            log.info("tool.deleted", tool_id=tool_id)
            return {"status": "deleted", "tool_id": tool_id}
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_preview_tool_ui(
        tool_id: str,
        ui: dict | None = None,  # type: ignore[type-arg]
        branding: dict | None = None,  # type: ignore[type-arg]
    ) -> dict:  # type: ignore[type-arg]
        """Build the MCP Apps HTML view for a tool — exactly what agents get at
        ``ui://<slug>/<tool_id>`` — so Studio can render it in its sandboxed
        preview. Pass ``ui`` (a ToolUIConfig-shaped dict) to preview a DRAFT
        view config without saving it to the tool first, and ``branding``
        (a ConnectorBranding-shaped dict) to preview draft accent/logo
        branding; otherwise the session's saved branding applies.
        """
        try:
            from pathlib import Path

            from elliot_core.apps import build_tool_app_html, ui_resource_uri
            from elliot_core.types.connector import ConnectorBranding
            from elliot_core.types.tool import ToolUIConfig

            tool = session.registry.get(tool_id)
            if tool is None:
                return {"error": f"Tool not found: {tool_id}"}
            ui_cfg = ToolUIConfig.model_validate(ui) if ui else (tool.ui or ToolUIConfig())
            branding_cfg = (
                ConnectorBranding.model_validate(branding)
                if branding is not None
                else session.branding
            )
            slug = session.connector.slug if session.connector else None
            connector_dir = Path(session.workspace._dir).resolve().parent
            html = build_tool_app_html(
                tool,
                ui_cfg,
                connector_slug=slug,
                connector_dir=connector_dir,
                branding=branding_cfg,
            )
            return {
                "tool_id": tool_id,
                "uri": ui_resource_uri(slug, tool_id),
                "html": html,
                "preset": ui_cfg.preset,
            }
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_validate_tool(tool: dict) -> dict:  # type: ignore[type-arg]
        """Validate a tool definition without saving it to the registry.

        Accepts the same loose input as elliot_create_tool: missing `id` is
        derived from `name`, and lowercase categories are normalized.
        """
        try:
            from elliot_core.tools.validator import validate_tool_definition

            normalized = _normalize_tool_input(tool)
            # M1: elliot_create_tool infers source_ids from the SQL, but
            # validate_tool used to demand them explicitly — so the same payload
            # validated differently depending on which tool you handed it to.
            # Infer here too: from the SQL when present, else all session
            # sources, so a READ tool isn't rejected for a missing source_id the
            # create path would have filled in.
            if normalized.get("category") == "READ" and not normalized.get("source_ids"):
                sql = normalized.get("sql")
                normalized["source_ids"] = (
                    _infer_source_ids_from_sql(str(sql), session)
                    if sql
                    else list(session.sources.keys())
                )
            validate_tool_definition(normalized)
            return {"valid": True}
        except ElliotError as exc:
            return {"valid": False, "error": exc.message}
        except Exception as exc:
            return {"valid": False, "error": str(exc)}

    @mcp.tool()
    async def elliot_preview_tool(
        tool_id: str,
        params: dict | None = None,  # type: ignore[type-arg]
        arguments: dict | None = None,  # type: ignore[type-arg]
        parameters: dict | None = None,  # type: ignore[type-arg]
    ) -> dict:  # type: ignore[type-arg]
        """Execute a tool against current data and return rows.

        SQL-backed tools run against the session's SQLite snapshot. REST
        passthrough tools (created with elliot_create_rest_tool) are fetched
        LIVE from their source with the supplied params, so they can be tested
        in-session before publish. Pass call-time values via 'params'
        (preferred), 'arguments', or 'parameters'.
        """
        try:
            supplied: dict[str, Any] = {}
            for src in (params, arguments, parameters):
                if src:
                    supplied.update(src)
            return await preview_tool_live(session, tool_id, supplied)
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("tool.preview.failed", tool_id=tool_id, error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))
