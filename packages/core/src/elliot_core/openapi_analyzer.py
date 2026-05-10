"""Analyze an OpenAPI 3.x spec and produce a ProposedConnector draft."""

from __future__ import annotations

import re
from typing import Any

import httpx
import structlog
from pydantic import BaseModel

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


def analyze_spec(spec: dict[str, Any] | str) -> ProposedConnector:
    """Parse an OpenAPI 3.x spec and return a ProposedConnector.

    `spec` can be a dict (already parsed) or a URL string.
    """
    if isinstance(spec, str):
        spec = _fetch_spec(spec)
    _validate_version(spec)

    info = spec.get("info", {})
    servers = spec.get("servers", [{}])
    base_url = servers[0].get("url", "").rstrip("/")
    slug = _slugify(info.get("title", "my-api"))

    source = ProposedSource(
        id="api",
        name=info.get("title", "API"),
        type="rest",
        base_url=base_url,
        auth_hint=_detect_auth(spec),
    )

    tools: list[ProposedTool] = []
    skipped = 0

    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            if method != "get":
                skipped += 1
                continue
            if not isinstance(operation, dict):
                continue
            tools.append(_build_tool(path, method, operation, spec))

    warnings: list[str] = []
    if skipped:
        warnings.append(
            f"{skipped} write endpoint(s) skipped (POST/PUT/PATCH/DELETE). "
            "Ask the agent to include them if needed."
        )
    if len(tools) > 20:
        warnings.append(
            f"{len(tools)} tools proposed. Consider keeping only the 5–10 most useful "
            "for agents — more tools increase token cost on every call."
        )

    log.info(
        "openapi.analyzed",
        slug=slug,
        tools=len(tools),
        skipped=skipped,
        warnings=len(warnings),
    )
    return ProposedConnector(
        name=info.get("title", "My API"),
        slug=slug,
        version=info.get("version", "1.0.0"),
        sources=[source],
        tools=tools,
        warnings=warnings,
    )


def _build_tool(
    path: str, method: str, operation: dict[str, Any], spec: dict[str, Any]
) -> ProposedTool:
    op_id = operation.get("operationId", "")
    summary = operation.get("summary", "")

    tool_id = _to_snake(op_id) if op_id else _path_to_id(path, method)
    name = summary or tool_id.replace("_", " ").title()
    description = _ensure_verb_first(operation.get("description", "") or summary or name)

    params = [
        ProposedParameter(
            name=p["name"],
            type=p.get("schema", {}).get("type", "string"),
            description=p.get("description", ""),
            required=p.get("required", False),
        )
        for p in operation.get("parameters", [])
        if isinstance(p, dict) and "name" in p
    ]

    response_fields = _extract_response_fields(operation, spec)
    token_risk = (
        "high" if len(response_fields) > 15 else "medium" if len(response_fields) > 7 else "low"
    )

    return ProposedTool(
        id=tool_id,
        name=name,
        description=description,
        category="READ",
        http_method=method.upper(),
        http_path=path,
        parameters=params,
        response_fields=response_fields,
        token_risk=token_risk,
    )


def _fetch_spec(url: str) -> dict[str, Any]:
    r = httpx.get(url, timeout=10, follow_redirects=True)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        try:
            import yaml

            return yaml.safe_load(r.text)
        except ImportError as exc:
            raise ValueError("YAML spec requires: pip install pyyaml") from exc


def _validate_version(spec: dict[str, Any]) -> None:
    if "openapi" not in spec:
        raise ValueError("Only OpenAPI 3.x specs are supported (missing 'openapi' key)")


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
    return None


def _extract_response_fields(operation: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    try:
        resp: dict[str, Any] = operation.get("responses", {}).get("200", {})
        content: dict[str, Any] = resp.get("content", {})
        first_val: Any = next(iter(content.values()), {})
        schema: dict[str, Any] = first_val.get("schema", {}) if isinstance(first_val, dict) else {}
        if "$ref" in schema:
            schema = _resolve_ref(schema["$ref"], spec)
        if schema.get("type") == "array":
            items: Any = schema.get("items", {})
            schema = items if isinstance(items, dict) else {}
            if "$ref" in schema:
                schema = _resolve_ref(schema["$ref"], spec)
        return list(schema.get("properties", {}).keys())
    except Exception:
        return []


def _resolve_ref(ref: str, spec: dict[str, Any]) -> dict[str, Any]:
    parts = ref.lstrip("#/").split("/")
    node: Any = spec
    for part in parts:
        node = node.get(part, {})
    return node


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _to_snake(s: str) -> str:
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", s)
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _path_to_id(path: str, method: str) -> str:
    parts = [p for p in path.split("/") if p and not p.startswith("{")]
    action = "list" if method == "get" and "{" not in path else "get"
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
