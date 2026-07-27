"""Analyze an OpenAPI 3.x (or Swagger 2.0) spec and produce a ProposedConnector draft.

The proposal is the "paste your API" onramp, so it must come out *buildable*:
absolute base URL, snake_case verb-first tool contracts, no colliding or
silently-dropped parameters, and a wired auth block — not a hint string.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import structlog
from pydantic import BaseModel

from elliot_core.naming import is_valid_identifier, slugify_identifier

log = structlog.get_logger(__name__)


class ProposedParameter(BaseModel):
    name: str
    type: str
    description: str
    required: bool


class ProposedTool(BaseModel):
    id: str
    name: str
    description: str
    category: str
    http_method: str
    http_path: str
    parameters: list[ProposedParameter]
    response_fields: list[str]
    token_risk: str


class ProposedSource(BaseModel):
    id: str
    name: str
    type: str
    base_url: str
    auth_hint: str | None
    # A ready-to-use ``auth`` block for elliot_discover_source, derived from the
    # spec's securitySchemes — with ``{{ env:NAME }}`` placeholders the user
    # fills as tenant secrets. ``None`` when the spec declares no auth.
    auth: dict[str, Any] | None = None


class ProposedConnector(BaseModel):
    name: str
    slug: str
    version: str
    sources: list[ProposedSource]
    tools: list[ProposedTool]
    warnings: list[str]


_HTTP_METHODS = ("get", "post", "put", "patch", "delete")

# OpenAPI HTTP method -> Elliot tool category. DELETE is destructive, so it
# maps to ACTION; the other writes map to WRITE.
_METHOD_CATEGORY = {
    "get": "READ",
    "post": "WRITE",
    "put": "WRITE",
    "patch": "WRITE",
    "delete": "ACTION",
}

# Leading words that make a description read as a verb-first contract. Keep
# aligned with the linter's DESCRIPTION_MISSING_VERB rule — the proposal must
# be born passing lint, not fixed after.
_LEADING_VERBS = frozenset(
    {
        "get",
        "gets",
        "list",
        "lists",
        "fetch",
        "fetches",
        "retrieve",
        "retrieves",
        "return",
        "returns",
        "search",
        "searches",
        "find",
        "finds",
        "query",
        "queries",
        "browse",
        "count",
        "counts",
        "read",
        "reads",
        "show",
        "shows",
        "describe",
        "describes",
        "create",
        "creates",
        "add",
        "adds",
        "insert",
        "inserts",
        "register",
        "registers",
        "place",
        "places",
        "submit",
        "submits",
        "post",
        "posts",
        "upload",
        "uploads",
        "import",
        "imports",
        "export",
        "exports",
        "update",
        "updates",
        "edit",
        "edits",
        "modify",
        "modifies",
        "patch",
        "patches",
        "set",
        "sets",
        "rename",
        "renames",
        "move",
        "moves",
        "merge",
        "merges",
        "assign",
        "assigns",
        "mark",
        "marks",
        "change",
        "changes",
        "replace",
        "replaces",
        "save",
        "saves",
        "store",
        "stores",
        "delete",
        "deletes",
        "remove",
        "removes",
        "destroy",
        "destroys",
        "drop",
        "drops",
        "purge",
        "purges",
        "clear",
        "clears",
        "cancel",
        "cancels",
        "revoke",
        "revokes",
        "disable",
        "disables",
        "enable",
        "enables",
        "activate",
        "activates",
        "deactivate",
        "deactivates",
        "archive",
        "archives",
        "restore",
        "restores",
        "send",
        "sends",
        "notify",
        "notifies",
        "trigger",
        "triggers",
        "execute",
        "executes",
        "run",
        "runs",
        "start",
        "starts",
        "stop",
        "stops",
        "pause",
        "pauses",
        "resume",
        "resumes",
        "sync",
        "syncs",
        "refresh",
        "refreshes",
        "validate",
        "validates",
        "verify",
        "verifies",
        "check",
        "checks",
        "calculate",
        "calculates",
        "compute",
        "computes",
        "generate",
        "generates",
        "build",
        "builds",
        "convert",
        "converts",
        "download",
        "downloads",
        "log",
        "logs",
        "login",
        "logout",
        "authenticate",
        "authenticates",
        "filter",
        "filters",
        "aggregate",
        "aggregates",
        "summarize",
        "summarizes",
        "rank",
        "ranks",
        "grade",
        "grades",
    }
)

_SYNTH_VERB = {
    "get": ("Get", "List"),  # (single item, collection)
    "post": ("Create", "Create"),
    "put": ("Update", "Update"),
    "patch": ("Update", "Update"),
    "delete": ("Delete", "Delete"),
}


def analyze_spec(spec: dict[str, Any] | str, spec_url: str | None = None) -> ProposedConnector:
    """Parse an OpenAPI 3.0 / 3.1 (or Swagger 2.0) spec into a ProposedConnector.

    ``spec`` can be a dict (already parsed) or a URL string. Every operation —
    read and write — becomes a proposed tool; ``$ref`` pointers in parameters,
    request bodies and responses are resolved. When the spec came from a URL,
    a relative ``servers[0].url`` is resolved against it so the proposed
    ``base_url`` is always absolute when it can be.
    """
    if isinstance(spec, str):
        spec_url = spec_url or spec
        spec = _fetch_spec(spec)

    warnings: list[str] = []
    if str(spec.get("swagger", "")).startswith("2"):
        spec = _convert_swagger2(spec)
        warnings.append(
            "Converted from Swagger 2.0 to OpenAPI 3 — review the proposed auth and "
            "request bodies before building."
        )
    _validate_version(spec)

    info = spec.get("info", {})
    base_url = _resolve_base_url(spec, spec_url, warnings)
    slug = _slugify(info.get("title", "my-api"))
    auth_hint, auth_block = _propose_auth(spec, slug)

    source = ProposedSource(
        id="api",
        name=info.get("title", "API"),
        type="rest",
        base_url=base_url,
        auth_hint=auth_hint,
        auth=auth_block,
    )

    tools: list[ProposedTool] = []
    seen_ids: set[str] = set()
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            tools.append(_build_tool(path, method, path_item, operation, spec, seen_ids, warnings))

    write_count = sum(1 for t in tools if t.category != "READ")
    if write_count:
        warnings.append(
            f"{write_count} write endpoint(s) (POST/PUT/PATCH/DELETE) became WRITE/ACTION "
            "tools — review them and drop any the agent should not be able to call."
        )
    if len(tools) > 20:
        warnings.append(
            f"{len(tools)} tools proposed. Consider keeping only the 5–10 most useful "
            "for agents — more tools increase token cost on every call."
        )

    log.info("openapi.analyzed", slug=slug, tools=len(tools), warnings=len(warnings))
    return ProposedConnector(
        name=info.get("title", "My API"),
        slug=slug,
        version=str(info.get("version", "1.0.0")),
        sources=[source],
        tools=tools,
        warnings=warnings,
    )


def _resolve_base_url(spec: dict[str, Any], spec_url: str | None, warnings: list[str]) -> str:
    """Return an absolute server URL whenever one can be derived.

    A relative ``servers[0].url`` (e.g. ``"/api/v3"``) is resolved against the
    URL the spec itself was fetched from — the exact case that previously
    produced a connector whose every request 404'd.
    """
    servers = spec.get("servers") or []
    first = servers[0] if servers and isinstance(servers[0], dict) else {}
    raw = str(first.get("url", "") or "").strip()
    for var, cfg in (first.get("variables") or {}).items():
        if isinstance(cfg, dict):
            raw = raw.replace("{" + str(var) + "}", str(cfg.get("default", "")))

    if raw and urlparse(raw).scheme in ("http", "https"):
        return raw.rstrip("/")
    if spec_url:
        return urljoin(spec_url, raw or "/").rstrip("/")
    if raw:
        warnings.append(
            f"Server URL {raw!r} is relative and the spec was not fetched from a URL — "
            "set the source base_url to the absolute API address before discovery."
        )
        return raw.rstrip("/")
    warnings.append(
        "Spec declares no servers — set the source base_url to the API address before discovery."
    )
    return ""


def _propose_auth(spec: dict[str, Any], slug: str) -> tuple[str | None, dict[str, Any] | None]:
    """Turn ``securitySchemes`` into a ready ``auth`` block, not just a hint.

    The scheme referenced by the spec's top-level ``security`` requirement wins;
    otherwise the first declared scheme. Secret values are emitted as
    ``{{ env:NAME }}`` placeholders for the user to fill as tenant secrets.
    """
    schemes = spec.get("components", {}).get("securitySchemes", {}) or {}
    preferred: list[str] = []
    for req in spec.get("security", []) or []:
        if isinstance(req, dict):
            preferred.extend(req.keys())
    ordered = [schemes[k] for k in preferred if isinstance(schemes.get(k), dict)]
    ordered += [s for k, s in schemes.items() if k not in preferred and isinstance(s, dict)]

    env = re.sub(r"[^A-Z0-9]+", "_", slug.upper()).strip("_") or "API"
    for scheme in ordered:
        t = scheme.get("type", "")
        if t == "apiKey":
            block: dict[str, Any] = {
                "type": "api_key",
                "secret_key": f"{{{{ env:{env}_API_KEY }}}}",
            }
            if scheme.get("in") == "query":
                block["query_param"] = scheme.get("name", "api_key")
            else:
                block["header_name"] = scheme.get("name", "X-API-Key")
            return "api_key", block
        if t == "http" and scheme.get("scheme") == "bearer":
            return "bearer", {"type": "bearer", "secret_key": f"{{{{ env:{env}_TOKEN }}}}"}
        if t == "http" and scheme.get("scheme") == "basic":
            return "basic", {
                "type": "basic",
                # Resolved value must be "user:password".
                "secret_key": f"{{{{ env:{env}_BASIC }}}}",
            }
        if t == "oauth2":
            flows = scheme.get("flows", {}) or {}
            flow = (
                flows.get("authorizationCode")
                or flows.get("implicit")
                or flows.get("clientCredentials")
                or {}
            )
            return "oauth2", {
                "type": "oauth2",
                "scope": "per_user",
                "secret_key": "{{ user_oauth:api }}",
                "oauth2": {
                    "authorization_url": flow.get("authorizationUrl", ""),
                    "token_url": flow.get("tokenUrl", ""),
                    "scopes": sorted((flow.get("scopes") or {}).keys()),
                    "client_id_secret": f"{{{{ env:{env}_CLIENT_ID }}}}",
                    "client_secret_secret": f"{{{{ env:{env}_CLIENT_SECRET }}}}",
                },
            }
    return None, None


def _build_tool(
    path: str,
    method: str,
    path_item: dict[str, Any],
    operation: dict[str, Any],
    spec: dict[str, Any],
    seen_ids: set[str],
    warnings: list[str],
) -> ProposedTool:
    op_id = operation.get("operationId", "")
    tool_id = _to_snake(op_id) if op_id else _path_to_id(path, method)
    if not is_valid_identifier(tool_id):
        tool_id = slugify_identifier(tool_id) or f"{method}_endpoint"
        if not is_valid_identifier(tool_id):
            tool_id = f"op_{tool_id}"
    while tool_id in seen_ids:
        tool_id = f"{tool_id}_{method}"
    seen_ids.add(tool_id)

    description = _compose_description(
        operation.get("summary", ""), operation.get("description", ""), method, path
    )

    # Path-level parameters apply to every operation on the path; merge them
    # with the operation's own, then add request-body fields for writes.
    params, seen_names = _collect_parameters(path_item, operation, spec, tool_id, warnings)
    params += _request_body_params(operation, spec, seen_names, tool_id, warnings)

    response_fields = _extract_response_fields(operation, spec)
    token_risk = (
        "high" if len(response_fields) > 15 else "medium" if len(response_fields) > 7 else "low"
    )

    return ProposedTool(
        id=tool_id,
        # The name IS the identifier — sentence-case titles with trailing
        # periods fail the snake_case naming lint and read badly in tool lists.
        name=tool_id,
        description=description,
        category=_METHOD_CATEGORY.get(method, "READ"),
        http_method=method.upper(),
        http_path=path,
        parameters=params,
        response_fields=response_fields,
        token_risk=token_risk,
    )


def _starts_with_verb(text: str) -> bool:
    first = text.split()[0].lower().strip(".,:;") if text.split() else ""
    return first in _LEADING_VERBS


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _compose_description(summary: str, description: str, method: str, path: str) -> str:
    """Build a verb-first contract from the operation's summary + description.

    Whichever of the two already leads with a verb becomes the head; the other
    becomes supporting detail. When neither does, a head is synthesized from
    the HTTP method and path ("Update a pet.") instead of bolting a literal
    "Return " prefix onto arbitrary prose — the old behaviour that produced
    contracts like "Return add a new pet to the store."
    """
    summary = (summary or "").strip()
    description = (description or "").strip()

    if summary and _starts_with_verb(summary):
        head, detail = summary, description
    elif description and _starts_with_verb(description):
        head, detail = description, summary
    else:
        head = _synth_head(method, path)
        detail = " ".join(x for x in (summary, description) if x)

    if detail:
        nh, nd = _norm(head), _norm(detail)
        if nd.startswith(nh) or nh.startswith(nd):
            # One is a prefix of the other — keep the more informative one.
            head, detail = (head if len(nh) >= len(nd) else detail), ""

    out = head if not detail else f"{head.rstrip('.')}. {detail}"
    out = out.strip()
    if out and out[0].islower():
        out = out[0].upper() + out[1:]
    return out


def _synth_head(method: str, path: str) -> str:
    segments = [p for p in path.split("/") if p]
    resource_parts = [p for p in segments if not p.startswith("{")]
    resource = resource_parts[-1] if resource_parts else "the API"
    resource = re.sub(r"[_\-]+", " ", resource)
    single, plural = _SYNTH_VERB.get(method, ("Call", "Call"))
    targets_one = bool(segments) and segments[-1].startswith("{")
    if method == "get":
        return f"{single} one {resource} by id." if targets_one else f"{plural} {resource}."
    return f"{single} a {resource}." if targets_one or method != "get" else f"{plural} {resource}."


def _collect_parameters(
    path_item: dict[str, Any],
    operation: dict[str, Any],
    spec: dict[str, Any],
    tool_id: str,
    warnings: list[str],
) -> tuple[list[ProposedParameter], set[str]]:
    """Merge path-level + operation parameters, resolving any ``$ref``.

    Header and cookie parameters are NOT proposed as tool parameters: auth
    material belongs in the source's ``auth`` block / static headers, never in
    an agent-facing parameter (an agent must not be asked to supply an api_key).
    """
    raw = list(path_item.get("parameters", []) or []) + list(operation.get("parameters", []) or [])
    out: list[ProposedParameter] = []
    seen: set[str] = set()
    skipped_headers: list[str] = []
    for p in raw:
        resolved = _deref(p, spec) if isinstance(p, dict) else {}
        name = resolved.get("name")
        if not name or name in seen:
            continue
        if resolved.get("in") in ("header", "cookie"):
            skipped_headers.append(str(name))
            continue
        seen.add(name)
        out.append(
            ProposedParameter(
                name=name,
                type=_schema_type(_deref(resolved.get("schema", {}), spec)),
                description=resolved.get("description", ""),
                required=bool(resolved.get("required", False)),
            )
        )
    if skipped_headers:
        warnings.append(
            f"{tool_id}: header/cookie parameter(s) {', '.join(sorted(skipped_headers))} "
            "were not proposed as tool parameters — configure them via the source's "
            "auth block or static headers instead."
        )
    return out, seen


def _request_body_params(
    operation: dict[str, Any],
    spec: dict[str, Any],
    seen: set[str],
    tool_id: str,
    warnings: list[str],
) -> list[ProposedParameter]:
    """Turn a write operation's requestBody schema into parameters.

    Handles the three real-world shapes instead of only flat objects:
    object-with-properties (one parameter per field, renamed on collision with
    a path/query parameter), top-level arrays (one ``items`` array parameter —
    previously dropped silently), and freeform objects (one ``body`` object
    parameter). Non-JSON bodies produce a warning, not silence.
    """
    body = _deref(operation.get("requestBody", {}), spec)
    content = body.get("content", {})
    if not isinstance(content, dict) or not content:
        return []
    if "application/json" in content:
        media, content_type = content["application/json"], "application/json"
    else:
        content_type, media = next(iter(content.items()))
    if not isinstance(media, dict):
        return []
    schema = _deref(media.get("schema", {}), spec)
    body_required = bool(body.get("required", False))

    if not str(content_type).startswith("application/json") and "form" not in str(content_type):
        warnings.append(
            f"{tool_id}: request body content type '{content_type}' (e.g. a file upload) "
            "is not mapped to parameters — add them manually if agents must supply it."
        )
        return []

    schema_kind = _schema_type(schema)
    if schema_kind == "array":
        item = _deref(schema.get("items", {}), spec)
        fields = list((item.get("properties") or {}).keys())
        desc = "JSON array request body."
        if fields:
            desc = f"JSON array of objects; each item has fields: {', '.join(fields[:12])}."
        name = "items" if "items" not in seen else "body_items"
        seen.add(name)
        return [
            ProposedParameter(name=name, type="array", description=desc, required=body_required)
        ]

    properties = schema.get("properties", {}) or {}
    if not properties:
        if schema_kind == "object" or schema:
            name = "body" if "body" not in seen else "body_payload"
            seen.add(name)
            return [
                ProposedParameter(
                    name=name,
                    type="object",
                    description="JSON object request body.",
                    required=body_required,
                )
            ]
        return []

    required = set(schema.get("required", []) or [])
    out: list[ProposedParameter] = []
    renamed: list[str] = []
    for field, field_schema in properties.items():
        resolved = _deref(field_schema, spec) if isinstance(field_schema, dict) else {}
        name = str(field)
        description = resolved.get("description", "")
        if name in seen:
            # A body field colliding with a path/query parameter (e.g. PUT
            # /user/{username} whose body also has "username") previously
            # produced two parameters with one name — an unbuildable tool.
            name = f"body_{name}"
            renamed.append(str(field))
            description = f"(request body field '{field}') {description}".strip()
        seen.add(name)
        out.append(
            ProposedParameter(
                name=name,
                type=_schema_type(resolved),
                description=description,
                required=field in required,
            )
        )
    if renamed:
        warnings.append(
            f"{tool_id}: body field(s) {', '.join(sorted(renamed))} collide with a "
            "path/query parameter and were renamed with a 'body_' prefix."
        )
    return out


def _fetch_spec(url: str) -> dict[str, Any]:
    # SSRF guard: the URL ultimately comes from agent / connector-builder input.
    from elliot_core.http import validate_url

    validate_url(url)
    r = httpx.get(url, timeout=10, follow_redirects=False)
    r.raise_for_status()
    try:
        parsed: Any = r.json()
    except Exception:
        parsed = parse_spec_text(r.text)
        return parsed
    if not isinstance(parsed, dict):
        raise ValueError("OpenAPI spec did not parse to a JSON/YAML object")
    return parsed


def parse_spec_text(text: str) -> dict[str, Any]:
    """Parse a pasted spec string — YAML or JSON — into a dict.

    Lets ``elliot_import_api_collection`` accept a pasted YAML spec, which
    previously only worked when the YAML was fetched from a URL.
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - pyyaml is a core dependency
        raise ValueError("YAML spec requires: pip install pyyaml") from exc
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("Spec did not parse to a JSON/YAML object")
    return parsed


def _validate_version(spec: dict[str, Any]) -> None:
    version = spec.get("openapi", "")
    if not version:
        raise ValueError("Only OpenAPI 3.x specs are supported (missing 'openapi' key)")
    if not str(version).startswith("3."):
        raise ValueError(f"Unsupported OpenAPI version {version!r}; only 3.0 and 3.1 are supported")


_SWAGGER_FLOW_NAMES = {
    "implicit": "implicit",
    "password": "password",
    "application": "clientCredentials",
    "accessCode": "authorizationCode",
}


def _convert_swagger2(spec: dict[str, Any]) -> dict[str, Any]:
    """Best-effort Swagger 2.0 → OpenAPI 3 conversion.

    Covers what real-world v2 specs use: host/basePath/schemes → servers,
    ``in: body`` / ``in: formData`` parameters → requestBody, response
    ``schema`` → content, securityDefinitions → securitySchemes, definitions →
    components.schemas with ``$ref`` rewriting. Exotic corners should be
    converted externally — but the common case must not bounce.
    """
    out: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": spec.get("info", {}),
        "paths": {},
        "components": {},
    }
    scheme = (spec.get("schemes") or ["https"])[0]
    host = spec.get("host", "")
    base_path = spec.get("basePath", "") or ""
    if host:
        out["servers"] = [{"url": f"{scheme}://{host}{base_path}".rstrip("/")}]
    elif base_path:
        out["servers"] = [{"url": base_path}]

    if spec.get("definitions"):
        out["components"]["schemas"] = spec["definitions"]
    sec: dict[str, Any] = {}
    for key, v in (spec.get("securityDefinitions") or {}).items():
        if not isinstance(v, dict):
            continue
        t = v.get("type")
        if t == "basic":
            sec[key] = {"type": "http", "scheme": "basic"}
        elif t == "apiKey":
            sec[key] = {"type": "apiKey", "name": v.get("name"), "in": v.get("in")}
        elif t == "oauth2":
            flow_name = _SWAGGER_FLOW_NAMES.get(str(v.get("flow", "")), "authorizationCode")
            sec[key] = {
                "type": "oauth2",
                "flows": {
                    flow_name: {
                        "authorizationUrl": v.get("authorizationUrl", ""),
                        "tokenUrl": v.get("tokenUrl", ""),
                        "scopes": v.get("scopes", {}) or {},
                    }
                },
            }
    if sec:
        out["components"]["securitySchemes"] = sec
    if "security" in spec:
        out["security"] = spec["security"]

    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        new_item: dict[str, Any] = {}
        shared = [p for p in (item.get("parameters") or []) if isinstance(p, dict)]
        for method, op in item.items():
            if method not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            new_op: dict[str, Any] = {
                k: v for k, v in op.items() if k in ("operationId", "summary", "description")
            }
            params: list[dict[str, Any]] = []
            body_param: dict[str, Any] | None = None
            form_props: dict[str, Any] = {}
            form_required: list[str] = []
            for p in shared + [q for q in (op.get("parameters") or []) if isinstance(q, dict)]:
                loc = p.get("in")
                if loc == "body":
                    body_param = p
                elif loc == "formData":
                    form_props[str(p.get("name", "field"))] = {
                        "type": p.get("type", "string"),
                        "description": p.get("description", ""),
                    }
                    if p.get("required"):
                        form_required.append(str(p.get("name")))
                else:
                    schema = {
                        k2: v2
                        for k2, v2 in p.items()
                        if k2
                        in ("type", "format", "enum", "items", "minimum", "maximum", "default")
                    }
                    params.append(
                        {
                            "name": p.get("name"),
                            "in": loc,
                            "required": bool(p.get("required", False)),
                            "description": p.get("description", ""),
                            "schema": schema or {"type": "string"},
                        }
                    )
            if params:
                new_op["parameters"] = params
            if body_param is not None:
                new_op["requestBody"] = {
                    "required": bool(body_param.get("required", False)),
                    "content": {"application/json": {"schema": body_param.get("schema", {})}},
                }
            elif form_props:
                form_schema: dict[str, Any] = {"type": "object", "properties": form_props}
                if form_required:
                    form_schema["required"] = form_required
                new_op["requestBody"] = {
                    "content": {"application/x-www-form-urlencoded": {"schema": form_schema}}
                }
            responses: dict[str, Any] = {}
            for code, r in (op.get("responses") or {}).items():
                if not isinstance(r, dict):
                    continue
                nr: dict[str, Any] = {"description": r.get("description", "")}
                if r.get("schema") is not None:
                    nr["content"] = {"application/json": {"schema": r["schema"]}}
                responses[str(code)] = nr
            if responses:
                new_op["responses"] = responses
            new_item[method] = new_op
        out["paths"][path] = new_item

    def _rewrite(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                k: (
                    v.replace("#/definitions/", "#/components/schemas/")
                    if k == "$ref" and isinstance(v, str)
                    else _rewrite(v)
                )
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [_rewrite(x) for x in node]
        return node

    converted: dict[str, Any] = _rewrite(out)
    return converted


def _extract_response_fields(operation: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    try:
        responses: dict[str, Any] = operation.get("responses", {})
        resp: dict[str, Any] = {}
        for code in ("200", "201", "default"):
            if isinstance(responses.get(code), dict):
                resp = responses[code]
                break
        content: dict[str, Any] = resp.get("content", {})
        first_val: Any = content.get("application/json") or next(iter(content.values()), {})
        schema = _deref(first_val.get("schema", {}) if isinstance(first_val, dict) else {}, spec)
        if _schema_type(schema) == "array":
            schema = _deref(schema.get("items", {}), spec)
        return list(schema.get("properties", {}).keys())
    except Exception:
        return []


def _deref(schema: Any, spec: dict[str, Any]) -> dict[str, Any]:
    """Follow a chain of local ``$ref`` pointers, with cycle protection."""
    seen: set[str] = set()
    while isinstance(schema, dict) and "$ref" in schema:
        ref = schema["$ref"]
        if ref in seen:
            return {}
        seen.add(ref)
        schema = _resolve_ref(ref, spec)
    return schema if isinstance(schema, dict) else {}


def _resolve_ref(ref: str, spec: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#/"):
        # External / remote refs are not fetched — fail soft.
        return {}
    node: Any = spec
    for part in ref[2:].split("/"):
        # JSON-pointer unescaping (~1 -> /, ~0 -> ~).
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict):
            return {}
        node = node.get(part, {})
    return node if isinstance(node, dict) else {}


def _schema_type(schema: dict[str, Any]) -> str:
    """Return a scalar type name, handling OpenAPI 3.1's list-valued ``type``."""
    t = schema.get("type", "string")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        return str(non_null[0]) if non_null else "string"
    return str(t)


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _to_snake(s: str) -> str:
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", s)
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _path_to_id(path: str, method: str) -> str:
    parts = [p for p in path.split("/") if p and not p.startswith("{")]
    has_path_param = "{" in path
    action = {
        "get": "get" if has_path_param else "list",
        "post": "create",
        "put": "update",
        "patch": "update",
        "delete": "delete",
    }.get(method, method)
    return "_".join([action] + parts) if parts else action
