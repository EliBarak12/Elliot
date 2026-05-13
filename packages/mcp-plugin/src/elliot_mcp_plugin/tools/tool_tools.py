"""Tool definition management — create, update, delete tools in the registry."""

from __future__ import annotations

from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.types.tool import ToolDefinition
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)

# Map friendly category names to valid ToolDefinition Literals
_CATEGORY_MAP: dict[str, str] = {
    "read": "READ",
    "write": "WRITE",
    "action": "ACTION",
    "aggregate": "READ",
}


def _normalize_tool_input(tool: dict[str, Any]) -> dict[str, Any]:
    """Accept the same loose shape that elliot_create_tool accepts.

    `elliot_create_tool` derives `id` from `name` and lower-cases the category,
    but `elliot_validate_tool` historically required the strict ToolDefinition
    shape (snake-case id, uppercase category). Apply the same normalizations
    here so an agent can hand the same payload to either tool.
    """
    out = dict(tool)
    if not out.get("id") and out.get("name"):
        out["id"] = str(out["name"])
    category = out.get("category")
    if isinstance(category, str):
        mapped = _CATEGORY_MAP.get(category.lower())
        if mapped is not None:
            out["category"] = mapped
    return out


def register_tool_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_create_tool(
        name: str,
        description: str,
        category: str,
        sql: str,
        parameters: list[dict],  # type: ignore[type-arg]
    ) -> dict:  # type: ignore[type-arg]
        """Define a new SQL-backed business tool and register it in the session."""
        try:
            if category.lower() not in _CATEGORY_MAP:
                valid = ", ".join(sorted(_CATEGORY_MAP))
                return {"error": f"Unknown category '{category}'. Valid: {valid}"}
            mapped_category = _CATEGORY_MAP[category.lower()]
            source_ids = list(session.sources.keys())
            tool = ToolDefinition.model_validate(
                {
                    "id": name,
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
            return {"tool_id": tool.id, "status": "created"}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("tool.create.failed", error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_update_tool(tool_id: str, patch: dict) -> dict:  # type: ignore[type-arg]
        """Partially update a tool definition (name, description, sql, parameters)."""
        try:
            tool = session.registry.get(tool_id)
            if tool is None:
                return {"error": f"Tool not found: {tool_id}"}
            sql_patch = patch.pop("sql", None)
            if patch:
                session.registry.update(tool_id, patch)
            if sql_patch is not None:
                session.tool_sql[tool_id] = sql_patch
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
            return {
                "tools": [t.model_dump() for t in session.registry.get_all()],
                "count": len(session.registry.get_all()),
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
    def elliot_validate_tool(tool: dict) -> dict:  # type: ignore[type-arg]
        """Validate a tool definition without saving it to the registry.

        Accepts the same loose input as elliot_create_tool: missing `id` is
        derived from `name`, and lowercase categories are normalized.
        """
        try:
            from elliot_core.tools.validator import validate_tool_definition

            validate_tool_definition(_normalize_tool_input(tool))
            return {"valid": True}
        except ElliotError as exc:
            return {"valid": False, "error": exc.message}
        except Exception as exc:
            return {"valid": False, "error": str(exc)}

    @mcp.tool()
    def elliot_preview_tool(
        tool_id: str,
        params: dict | None = None,  # type: ignore[type-arg]
        arguments: dict | None = None,  # type: ignore[type-arg]
        parameters: dict | None = None,  # type: ignore[type-arg]
    ) -> dict:  # type: ignore[type-arg]
        """Execute a tool's SQL against current SQLite data and return rows.

        Pass call-time values via 'params' (preferred), 'arguments', or 'parameters'.
        """
        try:
            tool = session.registry.get(tool_id)
            if tool is None:
                return {"error": f"Tool not found: {tool_id}"}
            sql = session.tool_sql.get(tool_id)
            if not sql:
                return {"error": f"No SQL defined for tool: {tool_id}"}

            supplied: dict[str, Any] = {}
            for src in (params, arguments, parameters):
                if src:
                    supplied.update(src)

            # Structured validation for missing required parameters so the agent
            # gets an actionable VALIDATION_REQUIRED error instead of a sqlite
            # 'datatype mismatch' downstream.
            missing = [
                p.name for p in tool.parameters if p.required and supplied.get(p.name) in (None, "")
            ]
            if missing:
                raise ElliotError(
                    "VALIDATION_REQUIRED",
                    f"Missing required parameter(s) for tool '{tool_id}': {', '.join(missing)}",
                    detail={"tool_id": tool_id, "missing": missing},
                )

            # Bind every declared parameter: caller-supplied value first, then
            # the declared default, finally None for fully-optional placeholders.
            bound: dict[str, object] = {}
            for p in tool.parameters:
                if p.name in supplied and supplied[p.name] not in (None, ""):
                    bound[p.name] = supplied[p.name]
                elif p.default is not None:
                    bound[p.name] = p.default
                else:
                    bound[p.name] = None
            rows = session.engine.query(sql, bound)
            return {"rows": rows, "row_count": len(rows)}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("tool.preview.failed", tool_id=tool_id, error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))
