"""Analyze a Postman Collection (v2.x) and produce a ProposedConnector draft.

Mirrors :mod:`elliot_core.openapi_analyzer` so the connector builder can ingest
whichever API description a product engineer already has — an OpenAPI spec or a
Postman collection export.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from elliot_core.openapi_analyzer import (
    ProposedConnector,
    ProposedParameter,
    ProposedSource,
    ProposedTool,
)

log = structlog.get_logger(__name__)

_CATEGORY_BY_METHOD = {
    "GET": "READ",
    "POST": "WRITE",
    "PUT": "WRITE",
    "PATCH": "WRITE",
    "DELETE": "ACTION",
}


def is_postman_collection(data: dict[str, Any]) -> bool:
    """Return True if ``data`` looks like a Postman Collection."""
    if "item" not in data:
        return False
    info = data.get("info", {})
    schema = str(info.get("schema", ""))
    return "getpostman.com" in schema or "_postman_id" in info or isinstance(data["item"], list)


def analyze_postman(collection: dict[str, Any] | str) -> ProposedConnector:
    """Parse a Postman Collection and return a :class:`ProposedConnector`."""
    data: dict[str, Any] = json.loads(collection) if isinstance(collection, str) else collection
    if not is_postman_collection(data):
        raise ValueError("Not a Postman Collection (missing 'item' array)")

    info = data.get("info", {})
    title = str(info.get("name", "My API"))
    slug = _slugify(title)

    # Collection-level variables ({{baseUrl}}, {{apiVersion}}, ...) are
    # substituted into URLs so requests resolve to real paths/hosts.
    variables = _collection_variables(data)

    requests: list[dict[str, Any]] = []
    _walk_items(data.get("item", []), requests)

    tools: list[ProposedTool] = []
    seen: set[str] = set()
    for req in requests:
        tool = _build_tool(req, variables)
        if tool is None:
            continue
        tool_id = tool.id
        suffix = 2
        while tool.id in seen:
            tool.id = f"{tool_id}_{suffix}"
            suffix += 1
        seen.add(tool.id)
        tools.append(tool)

    base_url = _detect_base_url(requests, variables)
    source = ProposedSource(
        id="api",
        name=title,
        type="rest",
        base_url=base_url,
        auth_hint=_detect_auth(data, requests),
    )

    warnings: list[str] = []
    write_tools = sum(1 for t in tools if t.category != "READ")
    if write_tools:
        warnings.append(
            f"{write_tools} write/action tool(s) detected — confirm with the user "
            "which mutations agents should be allowed to perform."
        )
    if len(tools) > 20:
        warnings.append(f"{len(tools)} tools proposed. Keep only the 5-15 most useful for agents.")
    if not tools:
        warnings.append("No HTTP requests found in the collection.")

    log.info("postman.analyzed", slug=slug, tools=len(tools), warnings=len(warnings))
    return ProposedConnector(
        name=title,
        slug=slug or "my-api",
        version="1.0.0",
        sources=[source],
        tools=tools,
        warnings=warnings,
    )


def _walk_items(items: list[Any], out: list[dict[str, Any]]) -> None:
    """Recursively collect request items, descending into folders."""
    for item in items:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("item"), list):
            _walk_items(item["item"], out)
        elif isinstance(item.get("request"), dict):
            out.append(item)


def _collection_variables(data: dict[str, Any]) -> dict[str, str]:
    """Build a {name: value} map from the collection's variable array."""
    out: dict[str, str] = {}
    for v in data.get("variable", []) or []:
        if isinstance(v, dict) and v.get("key"):
            out[str(v["key"])] = str(v.get("value", ""))
    return out


def _resolve_vars(text: str, variables: dict[str, str]) -> str:
    """Substitute {{var}} placeholders; unknown placeholders are left intact."""

    def _repl(m: re.Match[str]) -> str:
        return variables.get(m.group(1).strip(), m.group(0))

    return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", _repl, text)


def _build_tool(item: dict[str, Any], variables: dict[str, str]) -> ProposedTool | None:
    request = item["request"]
    method = str(request.get("method", "GET")).upper()
    if method not in _CATEGORY_BY_METHOD:
        return None

    url = request.get("url", {})
    raw_url, path, query_keys, path_vars = _parse_url(url, variables)
    name = str(item.get("name") or f"{method} {path}").strip()
    tool_id = _to_snake(name) or _to_snake(f"{method}_{path}")
    description = _ensure_verb_first(_request_description(request, item, method, path))

    params: list[ProposedParameter] = []
    for key in path_vars:
        params.append(
            ProposedParameter(
                name=_to_snake(key),
                type="string",
                description=f"Path value for '{key}'.",
                required=True,
            )
        )
    for key in query_keys:
        params.append(
            ProposedParameter(
                name=_to_snake(key),
                type="string",
                description=f"Query filter '{key}'.",
                required=False,
            )
        )
    for key in _body_keys(request):
        params.append(
            ProposedParameter(
                name=_to_snake(key),
                type="string",
                description=f"Request body field '{key}'.",
                required=method in ("POST", "PUT"),
            )
        )

    response_fields = _example_response_fields(item)
    token_risk = (
        "high" if len(response_fields) > 15 else "medium" if len(response_fields) > 7 else "low"
    )
    return ProposedTool(
        id=tool_id,
        name=name,
        description=description,
        category=_CATEGORY_BY_METHOD[method],
        http_method=method,
        http_path=path or raw_url,
        parameters=params,
        response_fields=response_fields,
        token_risk=token_risk,
    )


def _parse_url(url: Any, variables: dict[str, str]) -> tuple[str, str, list[str], list[str]]:
    """Return (raw_url, path, query_keys, path_variable_names)."""
    if isinstance(url, str):
        raw = _resolve_vars(url, variables)
        path = _path_from_raw(raw)
        return raw, path, [], _path_vars_from_path(path)
    if not isinstance(url, dict):
        return "", "", [], []
    raw = _resolve_vars(str(url.get("raw", "")), variables)
    segments = url.get("path", [])
    if isinstance(segments, list):
        path = "/" + "/".join(_resolve_vars(str(s), variables) for s in segments)
    else:
        path = _path_from_raw(raw)
    query_keys = [
        str(q["key"]) for q in url.get("query", []) if isinstance(q, dict) and q.get("key")
    ]
    path_vars = [
        str(v["key"]) for v in url.get("variable", []) if isinstance(v, dict) and v.get("key")
    ]
    path_vars += [v for v in _path_vars_from_path(path) if v not in path_vars]
    return raw, path, query_keys, path_vars


def _path_from_raw(raw: str) -> str:
    without_scheme = re.sub(r"^[a-z]+://", "", raw, flags=re.IGNORECASE)
    without_query = without_scheme.split("?", 1)[0]
    slash = without_query.find("/")
    return without_query[slash:] if slash >= 0 else "/"


def _path_vars_from_path(path: str) -> list[str]:
    return [seg[1:] for seg in path.split("/") if seg.startswith(":")]


def _body_keys(request: dict[str, Any]) -> list[str]:
    body = request.get("body", {})
    if not isinstance(body, dict):
        return []
    mode = body.get("mode")
    if mode == "raw":
        try:
            parsed = json.loads(body.get("raw", ""))
        except (json.JSONDecodeError, TypeError):
            return []
        return list(parsed.keys()) if isinstance(parsed, dict) else []
    if mode in ("urlencoded", "formdata"):
        entries = body.get(mode, [])
        return [str(e["key"]) for e in entries if isinstance(e, dict) and e.get("key")]
    return []


def _example_response_fields(item: dict[str, Any]) -> list[str]:
    for resp in item.get("response", []) or []:
        if not isinstance(resp, dict):
            continue
        try:
            parsed = json.loads(resp.get("body", "") or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return list(parsed[0].keys())
        if isinstance(parsed, dict):
            for value in parsed.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    return list(value[0].keys())
            return list(parsed.keys())
    return []


def _request_description(
    request: dict[str, Any], item: dict[str, Any], method: str, path: str
) -> str:
    desc = request.get("description") or item.get("description") or ""
    if isinstance(desc, dict):
        desc = desc.get("content", "")
    desc = str(desc).strip()
    return desc or f"{method} {path}"


def _detect_base_url(requests: list[dict[str, Any]], variables: dict[str, str]) -> str:
    for item in requests:
        url = item["request"].get("url", {})
        raw = url if isinstance(url, str) else str(url.get("raw", ""))
        match = re.match(r"(https?://[^/]+)", _resolve_vars(raw, variables))
        if match:
            return match.group(1)
    return ""


_AUTH_TYPE_HINT = {"bearer": "bearer", "apikey": "api_key", "basic": "basic", "oauth2": "oauth2"}


def _auth_hint_from_block(auth: Any) -> str | None:
    if isinstance(auth, dict):
        return _AUTH_TYPE_HINT.get(str(auth.get("type", "")))
    return None


def _detect_auth(collection: dict[str, Any], requests: list[dict[str, Any]]) -> str | None:
    # Collection-level auth is the common case; fall back to the first
    # request that declares its own auth block.
    hint = _auth_hint_from_block(collection.get("auth"))
    if hint:
        return hint
    for item in requests:
        hint = _auth_hint_from_block(item.get("request", {}).get("auth"))
        if hint:
            return hint
    return None


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _to_snake(s: str) -> str:
    s = re.sub(r"\{\{.*?\}\}", "", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


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
    "send",
    "add",
}


def _ensure_verb_first(s: str) -> str:
    s = s.strip()
    if not s:
        return ""
    if s.split()[0].lower() in _VERBS:
        return s
    return f"Return {s[0].lower()}{s[1:]}"
