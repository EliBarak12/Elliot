# Task 071 — Agentic Connector Builder (MCP Tools)

## Goal
Expose a set of MCP tools inside `elliot-mcp-plugin` that let an AI agent (Claude Code, Codex, or any MCP client) **build a connector interactively with the user**. The user connects their agent to Elliot, says "here's my API", and the agent drives the full connector-creation workflow using these tools — asking the user clarifying questions, proposing tools, refining descriptions, linting, and saving.

## Why this is the core product magic
Elliot is itself an agentic product. The user doesn't need to understand connector.json format, write SQL, or know what a jmespath expression is. They just talk to their agent:

```
User: I have a REST API at https://api.myapp.com — here's the OpenAPI spec.
       I want agents to be able to search users and create orders.

Agent: [calls analyze_api_spec → gets 12 proposed tools]
       I found 12 endpoints. For your use case I'd suggest 3 tools:
         1. search_users — searches by name/email
         2. get_user — gets a single user by ID  
         3. create_order — creates a new order
       
       For search_users, the API returns 'id', 'name', 'email', 'created_at',
       'last_login', 'preferences' (nested), 'billing_address' (nested).
       Which fields do agents actually need?

User: Just id, name, email is enough.

Agent: [calls update_tool_fields → trims response to 3 fields]
       [calls run_draft_lint → 1 warning: description doesn't start with verb]
       [calls update_tool_description → fixes it]
       [calls save_connector → writes file]
       Done. Your connector is saved as my-app.connector.json.
       Run `elliot eval my-app.eval.yaml` to test it.
```

## File to create

### `packages/mcp-plugin/src/elliot_mcp_plugin/tools/builder_tools.py`

```python
from __future__ import annotations
import json
import uuid
from pathlib import Path
from typing import Any

from elliot_core.openapi_analyzer import analyze_spec, ProposedConnector
from elliot_core.linter import lint_connector
from elliot_core.types import ConnectorConfig

# In-memory drafts per session — keyed by draft_id
_drafts: dict[str, dict] = {}


def get_builder_tools(connectors_dir: Path):
    """Return the list of MCP tool definitions for the agentic builder."""
    return [
        analyze_api_spec,
        list_drafts,
        create_draft,
        update_tool_in_draft,
        remove_tool_from_draft,
        add_tool_to_draft,
        run_draft_lint,
        save_draft,
        discard_draft,
        list_saved_connectors,
    ]


def analyze_api_spec(spec_url_or_json: str) -> dict:
    """
    Analyze an OpenAPI spec and return a proposed connector structure.
    Pass a URL (https://...) or raw JSON string.
    Returns proposed tools with descriptions, parameters, and token risk per tool.
    The agent should show this to the user and ask which tools to keep.
    """
    try:
        spec = json.loads(spec_url_or_json) if spec_url_or_json.strip().startswith("{") else spec_url_or_json
        proposed = analyze_spec(spec)
        return proposed.model_dump()
    except Exception as exc:
        return {"error": str(exc)}


def create_draft(proposed_connector_json: str) -> dict:
    """
    Create a new connector draft from a ProposedConnector JSON (output of analyze_api_spec).
    Returns a draft_id to use in subsequent calls.
    The agent should filter the proposed tools to only those the user needs before calling this.
    """
    draft_id = uuid.uuid4().hex[:8]
    _drafts[draft_id] = json.loads(proposed_connector_json)
    return {"draft_id": draft_id, "tool_count": len(_drafts[draft_id].get("tools", []))}


def list_drafts() -> list[dict]:
    """List all active connector drafts in this session."""
    return [
        {"draft_id": did, "name": d.get("name"), "tool_count": len(d.get("tools", []))}
        for did, d in _drafts.items()
    ]


def update_tool_in_draft(draft_id: str, tool_id: str, updates_json: str) -> dict:
    """
    Update a specific tool in a draft. `updates_json` is a partial tool object.
    Use this to refine descriptions, trim response_fields, rename parameters,
    or change the tool category. Only the provided fields are updated.
    """
    draft = _drafts.get(draft_id)
    if not draft:
        return {"error": f"No draft with id {draft_id}"}
    updates = json.loads(updates_json)
    for tool in draft.get("tools", []):
        if tool["id"] == tool_id:
            tool.update(updates)
            return {"ok": True, "tool": tool}
    return {"error": f"Tool '{tool_id}' not found in draft"}


def remove_tool_from_draft(draft_id: str, tool_id: str) -> dict:
    """Remove a tool from a draft. Use when the user says they don't need a particular tool."""
    draft = _drafts.get(draft_id)
    if not draft:
        return {"error": f"No draft with id {draft_id}"}
    before = len(draft["tools"])
    draft["tools"] = [t for t in draft["tools"] if t["id"] != tool_id]
    return {"removed": before - len(draft["tools"])}


def add_tool_to_draft(draft_id: str, tool_json: str) -> dict:
    """
    Add a new custom tool to a draft. `tool_json` must be a full ProposedTool object.
    Use this to add tools the OpenAPI spec didn't expose, or write operations the
    user explicitly wants (create, update, delete).
    """
    draft = _drafts.get(draft_id)
    if not draft:
        return {"error": f"No draft with id {draft_id}"}
    tool = json.loads(tool_json)
    draft.setdefault("tools", []).append(tool)
    return {"ok": True, "total_tools": len(draft["tools"])}


def run_draft_lint(draft_id: str) -> dict:
    """
    Run the tool quality linter on a draft.
    Returns a list of issues with severity, location, and fix suggestions.
    The agent should present errors to the user and ask for their input to fix them.
    """
    draft = _drafts.get(draft_id)
    if not draft:
        return {"error": f"No draft with id {draft_id}"}
    try:
        config = ConnectorConfig(**draft)
        issues = lint_connector(config)
        return {
            "issues": [i.model_dump() for i in issues],
            "errors": sum(1 for i in issues if i.severity == "error"),
            "warnings": sum(1 for i in issues if i.severity == "warning"),
        }
    except Exception as exc:
        return {"error": str(exc)}


def save_draft(draft_id: str, filename: str, connectors_dir: str) -> dict:
    """
    Save a draft as a .connector.json file.
    `filename` should end in .connector.json, e.g. "my-api.connector.json".
    Saved to connectors_dir on the server.
    Returns the full path so the user knows where to find it.
    """
    draft = _drafts.get(draft_id)
    if not draft:
        return {"error": f"No draft with id {draft_id}"}
    if not filename.endswith(".connector.json"):
        filename = filename.rstrip(".json") + ".connector.json"
    out = Path(connectors_dir) / filename
    out.write_text(json.dumps(draft, indent=2))
    del _drafts[draft_id]
    return {"saved": str(out), "tools": len(draft.get("tools", []))}


def discard_draft(draft_id: str) -> dict:
    """Discard a draft without saving. Use if the user wants to start over."""
    removed = _drafts.pop(draft_id, None)
    return {"discarded": removed is not None}


def list_saved_connectors(connectors_dir: str) -> list[dict]:
    """
    List all saved .connector.json files.
    Returns name, slug, version, tool count for each.
    """
    result = []
    for f in Path(connectors_dir).glob("*.connector.json"):
        try:
            data = json.loads(f.read_text())
            result.append({
                "file": f.name,
                "name": data.get("name"),
                "slug": data.get("slug"),
                "version": data.get("version"),
                "tools": len(data.get("tools", [])),
            })
        except Exception:
            result.append({"file": f.name, "error": "parse error"})
    return result
```

## What this enables — example agent session

```
1. User: "I have an API at https://api.pets.com — here's the spec: <URL>"
2. Agent: analyze_api_spec("https://api.pets.com/openapi.json")
          → 12 tools proposed, 3 HIGH token risk
3. Agent: "I see 12 endpoints. For a read-only agent you probably only need:
            list_pets, get_pet, search_pets. The others are write operations.
            The 'list_inventory' endpoint has HIGH token risk — it has no limit.
            Should I include it?"
4. User: "Skip inventory. Include the 3 read ones and also create_order."
5. Agent: create_draft(filtered_proposed_json)
          → draft_id: a3f9b1
6. Agent: "For list_pets, the response has 23 fields including nested objects.
            Which do agents actually need?"
7. User: "Just id, name, species, status."
8. Agent: update_tool_in_draft("a3f9b1", "list_pets", 
            '{"response_fields": ["id", "name", "species", "status"]}')
9. Agent: run_draft_lint("a3f9b1")
          → 2 warnings: create_order description missing verb, search_pets has param 'q'
10. Agent: fixes both automatically, asks user to confirm
11. Agent: save_draft("a3f9b1", "pets.connector.json", "/app/connectors")
           → "Saved to /app/connectors/pets.connector.json with 4 tools.
              Run: elliot eval pets.eval.yaml to test it."
```

## Tests

```python
def test_analyze_and_create_draft():
    result = analyze_api_spec("https://petstore3.swagger.io/api/v3/openapi.json")
    assert "tools" in result
    assert len(result["tools"]) > 0

def test_draft_lifecycle(tmp_path):
    draft = create_draft(json.dumps({
        "name": "Test", "slug": "test", "version": "1.0",
        "sources": [], "tools": [{"id": "list_items", "name": "List", 
            "description": "List all items", "category": "READ",
            "http_method": "GET", "http_path": "/items", "parameters": [],
            "response_fields": [], "token_risk": "low"}],
        "warnings": []
    }))
    did = draft["draft_id"]
    update_tool_in_draft(did, "list_items", '{"description": "Return all items"}')
    result = save_draft(did, "test.connector.json", str(tmp_path))
    assert (tmp_path / "test.connector.json").exists()
```

## Estimate
8–10 hours
