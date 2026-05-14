"""Agentic connector builder MCP tools.

An AI agent calls these tools to interactively build a connector with the user:
analyze an OpenAPI spec → create a draft → refine tools → lint → save.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# In-memory drafts per session, keyed by draft_id
_drafts: dict[str, dict[str, Any]] = {}


def analyze_api_spec(spec_url_or_json: str) -> dict[str, Any]:
    """Analyze an OpenAPI spec and return a proposed connector structure.

    Pass a URL (https://...) or raw JSON string of an OpenAPI 3.x spec.
    Returns proposed tools with descriptions, parameters, and token risk per tool.
    Show the result to the user and ask which tools to keep before creating a draft.
    """
    from elliot_core.openapi_analyzer import analyze_spec

    try:
        spec: dict[str, Any] | str = spec_url_or_json
        if spec_url_or_json.strip().startswith("{"):
            spec = json.loads(spec_url_or_json)
        proposed = analyze_spec(spec)
        log.info("builder.analyze_api_spec", slug=proposed.slug, tools=len(proposed.tools))
        return proposed.model_dump()
    except Exception as exc:
        log.warning("builder.analyze_api_spec.error", error=str(exc))
        return {"error": str(exc)}


def create_draft(proposed_connector_json: str) -> dict[str, Any]:
    """Create a new connector draft from a ProposedConnector JSON.

    Filter the proposed tools to only those the user needs before calling this.
    Returns a draft_id to use in subsequent calls.
    """
    try:
        data = json.loads(proposed_connector_json)
        draft_id = uuid.uuid4().hex[:8]
        _drafts[draft_id] = data
        tool_count = len(data.get("tools", []))
        log.info("builder.create_draft", draft_id=draft_id, tools=tool_count)
        return {"draft_id": draft_id, "tool_count": tool_count}
    except Exception as exc:
        return {"error": str(exc)}


def list_drafts() -> list[dict[str, Any]]:
    """List all active connector drafts in this session."""
    return [
        {"draft_id": did, "name": d.get("name"), "tool_count": len(d.get("tools", []))}
        for did, d in _drafts.items()
    ]


def update_tool_in_draft(draft_id: str, tool_id: str, updates_json: str) -> dict[str, Any]:
    """Update a specific tool in a draft with partial fields.

    Use this to refine descriptions, trim response_fields, rename parameters,
    or change the tool category. Only the provided fields are updated.
    """
    draft = _drafts.get(draft_id)
    if not draft:
        return {"error": f"No draft with id {draft_id!r}"}
    try:
        updates = json.loads(updates_json)
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid JSON: {exc}"}
    for tool in draft.get("tools", []):
        if tool.get("id") == tool_id:
            tool.update(updates)
            return {"ok": True, "tool": tool}
    return {"error": f"Tool {tool_id!r} not found in draft"}


def remove_tool_from_draft(draft_id: str, tool_id: str) -> dict[str, Any]:
    """Remove a tool from a draft.

    Use when the user says they don't need a particular tool.
    """
    draft = _drafts.get(draft_id)
    if not draft:
        return {"error": f"No draft with id {draft_id!r}"}
    before = len(draft.get("tools", []))
    draft["tools"] = [t for t in draft.get("tools", []) if t.get("id") != tool_id]
    return {"removed": before - len(draft["tools"])}


def add_tool_to_draft(draft_id: str, tool_json: str) -> dict[str, Any]:
    """Add a new custom tool to a draft.

    `tool_json` must be a full ProposedTool object.
    Use this to add tools the OpenAPI spec didn't expose, or write operations
    the user explicitly wants (create, update, delete).
    """
    draft = _drafts.get(draft_id)
    if not draft:
        return {"error": f"No draft with id {draft_id!r}"}
    try:
        tool = json.loads(tool_json)
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid JSON: {exc}"}
    draft.setdefault("tools", []).append(tool)
    return {"ok": True, "total_tools": len(draft["tools"])}


def run_draft_lint(draft_id: str) -> dict[str, Any]:
    """Run the tool quality linter on a draft.

    Returns issues with severity, location, and fix suggestions.
    Present errors to the user and ask for their input to fix them.
    """
    from elliot_core.linter import lint_connector
    from elliot_core.types import ConnectorConfig

    draft = _drafts.get(draft_id)
    if not draft:
        return {"error": f"No draft with id {draft_id!r}"}
    import dataclasses

    try:
        config = ConnectorConfig(**draft)
        issues = lint_connector(config)
        return {
            "issues": [dataclasses.asdict(i) for i in issues],
            "errors": sum(1 for i in issues if i.severity == "ERROR"),
            "warnings": sum(1 for i in issues if i.severity == "WARN"),
        }
    except Exception as exc:
        return {"error": str(exc)}


def save_draft(draft_id: str, filename: str, connectors_dir: str) -> dict[str, Any]:
    """Save a draft as a .connector.json file.

    `filename` should end in .connector.json, e.g. "my-api.connector.json".
    Saved to connectors_dir. Returns the full path so the user knows where to find it.
    """
    draft = _drafts.get(draft_id)
    if not draft:
        return {"error": f"No draft with id {draft_id!r}"}
    if not filename.endswith(".connector.json"):
        filename = filename.rstrip(".json") + ".connector.json"
    out = Path(connectors_dir) / filename
    # Atomic write so a crash mid-write can't leave a truncated
    # .connector.json on disk (audit Low 33).
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(draft, indent=2), encoding="utf-8")
    import os as _os

    _os.replace(tmp, out)
    del _drafts[draft_id]
    tool_count = len(draft.get("tools", []))
    log.info("builder.save_draft", path=str(out), tools=tool_count)
    return {"saved": str(out), "tools": tool_count}


def discard_draft(draft_id: str) -> dict[str, Any]:
    """Discard a draft without saving.

    Use if the user wants to start over.
    """
    removed = _drafts.pop(draft_id, None)
    return {"discarded": removed is not None}


def list_saved_connectors(connectors_dir: str) -> list[dict[str, Any]]:
    """List all saved .connector.json files.

    Returns name, slug, version, and tool count for each.
    """
    result: list[dict[str, Any]] = []
    for f in sorted(Path(connectors_dir).glob("*.connector.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append(
                {
                    "file": f.name,
                    "name": data.get("name"),
                    "slug": data.get("slug"),
                    "version": data.get("version"),
                    "tools": len(data.get("tools", [])),
                }
            )
        except Exception:
            result.append({"file": f.name, "error": "parse error"})
    return result
