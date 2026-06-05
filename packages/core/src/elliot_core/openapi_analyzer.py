"""Analyze an OpenAPI 3.x spec and produce a ProposedConnector draft."""

from __future__ import annotations

import re
from typing import Any

import httpx
import structlog
from pydantic import BaseModel

from elliot_core.naming import slugify

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


def analyze_spec(spec: dict[str, Any] | str) -> ProposedConnector:
    """Parse an OpenAPI 3.0 / 3.1 spec and return a ProposedConnector.

    `spec` can be a dict (already parsed) or a URL string. Every operation —
    read and write — becomes a proposed tool; ``$ref`` pointers in parameters,
    request bodies and responses are resolved.
    """
    if isinstance(spec, str):
        spec = _fetch_spec(spec)
    _validate_version(spec)

    info = spec.get("info", {})
    servers = spec.get("servers", [{}])
    base_url = (servers[0].get("url", "") if servers else "").rstrip("/")
    slug = slugify(info.get("title", "my-api"))

    source = ProposedSource(
        id="api",
        name=info.get("title", "API"),
        type="rest",
        base_url=base_url,
        auth_hint=_detect_auth(spec),
    )

    tools: list[ProposedTool] = []
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            tools.append(_build_tool(path, method, path_item, operation, spec))

    warnings: list[str] = []
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


def _build_tool(
    path: str,
    method: str,
    path_item: dict[str, Any],
    operation: dict[str, Any],
    spec: dict[str, Any],
) -> ProposedTool:
    op_id = operation.get("operationId", "")
    summary = operation.get("summary", "")

    tool_id = _to_snake(op_id) if op_id else _path_to_id(path, method)
    name = summary or tool_id.replace("_", " ").title()
    description = _ensure_verb_first(operation.get("description", "") or summary or name)

    # Path-level parameters apply to every operation on the path; merge them
    # with the operation's own, then add request-body fields for writes.
    params = _collect_parameters(path_item, operation, spec)
    params += _request_body_params(operation, spec)

    response_fields = _extract_response_fields(operation, spec)
    token_risk = (
        "high" if len(response_fields) > 15 else "medium" if len(response_fields) > 7 else "low"
    )

    return ProposedTool(
        id=tool_id,
        name=name,
        description=description,
        category=_METHOD_CATEGORY.get(method, "READ"),
        http_method=method.upper(),
        http_path=path,
        parameters=params,
        response_fields=response_fields,
        token_risk=token_risk,
    )


def _collect_parameters(
    path_item: dict[str, Any], operation: dict[str, Any], spec: dict[str, Any]
) -> list[ProposedParameter]:
    """Merge path-level + operation parameters, resolving any ``$ref``."""
    raw = list(path_item.get("parameters", []) or []) + list(operation.get("parameters", []) or [])
    out: list[ProposedParameter] = []
    seen: set[str] = set()
    for p in raw:
        resolved = _deref(p, spec) if isinstance(p, dict) else {}
        if "name" not in resolved or resolved["name"] in seen:
            continue
        seen.add(resolved["name"])
        out.append(
            ProposedParameter(
                name=resolved["name"],
                type=_schema_type(_deref(resolved.get("schema", {}), spec)),
                description=resolved.get("description", ""),
                required=bool(resolved.get("required", False)),
            )
        )
    return out


def _request_body_params(
    operation: dict[str, Any], spec: dict[str, Any]
) -> list[ProposedParameter]:
    """Turn a write operation's requestBody JSON schema into parameters."""
    body = _deref(operation.get("requestBody", {}), spec)
    content = body.get("content", {})
    if not isinstance(content, dict):
        return []
    media = content.get("application/json") or next(iter(content.values()), None)
    if not isinstance(media, dict):
        return []
    schema = _deref(media.get("schema", {}), spec)
    required = set(schema.get("required", []) or [])
    out: list[ProposedParameter] = []
    for field, field_schema in (schema.get("properties", {}) or {}).items():
        resolved = _deref(field_schema, spec) if isinstance(field_schema, dict) else {}
        out.append(
            ProposedParameter(
                name=field,
                type=_schema_type(resolved),
                description=resolved.get("description", ""),
                required=field in required,
            )
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
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("YAML spec requires: pip install pyyaml") from exc
        parsed = yaml.safe_load(r.text)
    if not isinstance(parsed, dict):
        raise ValueError("OpenAPI spec did not parse to a JSON/YAML object")
    return parsed


def _validate_version(spec: dict[str, Any]) -> None:
    version = spec.get("openapi", "")
    if not version:
        if "swagger" in spec:
            raise ValueError("Swagger 2.0 specs are not supported — convert to OpenAPI 3.x")
        raise ValueError("Only OpenAPI 3.x specs are supported (missing 'openapi' key)")
    if not str(version).startswith("3."):
        raise ValueError(f"Unsupported OpenAPI version {version!r}; only 3.0 and 3.1 are supported")


def _detect_auth(spec: dict[str, Any]) -> str | None:
    schemes = spec.get("components", {}).get("securitySchemes", {})
    for scheme in schemes.values():
        if not isinstance(scheme, dict):
            continue
        t = scheme.get("type", "")
        if t == "apiKey":
            return "api_key"
        if t == "http" and scheme.get("scheme") == "bearer":
            return "bearer"
        if t == "http" and scheme.get("scheme") == "basic":
            return "basic"
        if t == "oauth2":
            return "oauth2"
    return None


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


_VERBS = {
    "get",
    "return",
    "list",
    "fetch",
    "retrieve",
    "create",
    "update",
    "delete",
    "remove",
    "search",
}


def _ensure_verb_first(s: str) -> str:
    if not s:
        return ""
    if s.split()[0].lower() in _VERBS:
        return s
    return f"Return {s[0].lower()}{s[1:]}"
