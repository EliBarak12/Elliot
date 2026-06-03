# Task 070 — OpenAPI Spec Analyzer

## Goal
Create `elliot_core/openapi_analyzer.py`: a module that reads an OpenAPI 3.x spec (URL or dict) and produces a `ProposedConnector` — a ready-to-review connector.json draft with suggested sources, tools, descriptions, and parameters. This is the engine used by the agentic builder (task 071) and the CLI.

## Why
The hardest part of building a connector is the blank page. A user with an existing OpenAPI spec already has 80% of the information Elliot needs: endpoint paths, HTTP methods, parameter names and types, response schemas, and descriptions. The analyzer extracts all of this and turns it into a first-pass connector that the user (or their agent) can refine.

## File to create

### `packages/core/src/elliot_core/openapi_analyzer.py`

```python
from __future__ import annotations

import re
from typing import Any

import httpx
from pydantic import BaseModel


class ProposedParameter(BaseModel):
    name: str
    type: str  # string | integer | number | boolean
    description: str
    required: bool


class ProposedTool(BaseModel):
    id: str               # snake_case, e.g. "list_pets"
    name: str             # human label, e.g. "List Pets"
    description: str      # verb-first, e.g. "Return all pets, optionally filtered by status"
    category: str         # READ | WRITE | ACTION
    http_method: str
    http_path: str
    parameters: list[ProposedParameter]
    response_fields: list[str]  # top-level fields from response schema
    token_risk: str       # low | medium | high — estimated based on response shape


class ProposedSource(BaseModel):
    id: str
    name: str
    type: str  # rest
    base_url: str
    auth_hint: str | None  # e.g. "api_key", "bearer" — detected from securitySchemes


class ProposedConnector(BaseModel):
    name: str
    slug: str
    version: str
    sources: list[ProposedSource]
    tools: list[ProposedTool]
    warnings: list[str]   # e.g. "12 endpoints skipped (POST/PUT/DELETE)"


def analyze_spec(spec: dict | str) -> ProposedConnector:
    """
    Parse an OpenAPI 3.x spec and return a ProposedConnector.
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
    warnings: list[str] = []
    skipped = 0

    for path, path_item in spec.get("paths", {}).items():
        for method, operation in path_item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            if method != "get":
                skipped += 1
                continue  # default: only propose READ tools; agent can ask to include writes
            tool = _build_tool(path, method, operation, spec)
            tools.append(tool)

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

    return ProposedConnector(
        name=info.get("title", "My API"),
        slug=slug,
        version=info.get("version", "1.0.0"),
        sources=[source],
        tools=tools,
        warnings=warnings,
    )


def _build_tool(path: str, method: str, operation: dict, spec: dict) -> ProposedTool:
    op_id = operation.get("operationId", "")
    summary = operation.get("summary", "")
    description = operation.get("description", summary)

    tool_id = _to_snake(op_id) if op_id else _path_to_id(path, method)
    name = summary or tool_id.replace("_", " ").title()
    description = _ensure_verb_first(description or name)

    params = [
        ProposedParameter(
            name=p["name"],
            type=p.get("schema", {}).get("type", "string"),
            description=p.get("description", ""),
            required=p.get("required", False),
        )
        for p in operation.get("parameters", [])
    ]

    response_fields = _extract_response_fields(operation, spec)
    token_risk = "high" if len(response_fields) > 15 else "medium" if len(response_fields) > 7 else "low"

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


# ── helpers ──────────────────────────────────────────────────────────────────

def _fetch_spec(url: str) -> dict:
    import json, yaml  # yaml only if available
    r = httpx.get(url, timeout=10, follow_redirects=True)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        try:
            import yaml
            return yaml.safe_load(r.text)
        except ImportError:
            raise ValueError("YAML spec requires: pip install pyyaml")


def _validate_version(spec: dict) -> None:
    if "openapi" not in spec:
        raise ValueError("Only OpenAPI 3.x specs are supported")


def _detect_auth(spec: dict) -> str | None:
    schemes = spec.get("components", {}).get("securitySchemes", {})
    for scheme in schemes.values():
        t = scheme.get("type", "")
        if t == "apiKey":
            return "api_key"
        if t == "http" and scheme.get("scheme") == "bearer":
            return "bearer"
    return None


def _extract_response_fields(operation: dict, spec: dict) -> list[str]:
    try:
        resp = operation.get("responses", {}).get("200", {})
        content = resp.get("content", {})
        schema = next(iter(content.values()), {}).get("schema", {})
        # resolve $ref
        if "$ref" in schema:
            schema = _resolve_ref(schema["$ref"], spec)
        if schema.get("type") == "array":
            schema = schema.get("items", {})
            if "$ref" in schema:
                schema = _resolve_ref(schema["$ref"], spec)
        return list(schema.get("properties", {}).keys())
    except Exception:
        return []


def _resolve_ref(ref: str, spec: dict) -> dict:
    parts = ref.lstrip("#/").split("/")
    node = spec
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
    action = "list" if method == "get" and not any("{" in s for s in path.split("/")) else "get"
    return "_".join([action] + parts)


_VERBS = {"get", "return", "list", "fetch", "retrieve", "create", "update", "delete", "remove", "search"}


def _ensure_verb_first(s: str) -> str:
    if s and s.split()[0].lower() in _VERBS:
        return s
    return f"Return {s[0].lower() + s[1:]}" if s else ""
```

## CLI

```bash
# Analyze and print a summary
elliot analyze https://petstore3.swagger.io/api/v3/openapi.json

# Output:
# Pet Store  (petstore v1.0.0)
# Source:  https://petstore3.swagger.io
# Auth:    bearer
# Tools proposed (5):
#   ✓  list_pets         GET  /pet         low risk
#   ✓  get_pet_by_id     GET  /pet/{id}    low risk
#   ✓  find_pets_by_status GET /pet/findByStatus  medium risk
#   ✓  list_inventory    GET  /store/inventory    HIGH risk  ← no LIMIT possible
#   ✓  get_order         GET  /store/order/{id}   low risk
# Warnings:
#   - 8 write endpoints skipped
#   - list_inventory may return unbounded data — add filtering parameters
```

## Estimate
6–8 hours
