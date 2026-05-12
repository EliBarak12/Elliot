"""Tool definition management — create, update, delete tools in the registry."""

from __future__ import annotations

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
        """Validate a tool definition without saving it to the registry."""
        try:
            from elliot_core.tools.validator import validate_tool_definition

            validate_tool_definition(tool)
            return {"valid": True}
        except ElliotError as exc:
            return {"valid": False, "error": exc.message}
        except Exception as exc:
            return {"valid": False, "error": str(exc)}

    @mcp.tool()
    def elliot_preview_tool(tool_id: str, params: dict) -> dict:  # type: ignore[type-arg]
        """Execute a tool's SQL against current SQLite data and return rows."""
        try:
            tool = session.registry.get(tool_id)
            if tool is None:
                return {"error": f"Tool not found: {tool_id}"}
            sql = session.tool_sql.get(tool_id)
            if not sql:
                return {"error": f"No SQL defined for tool: {tool_id}"}
            # Pre-fill all declared parameters with None so optional params don't cause bind errors
            null_filled: dict[str, object] = {p.name: None for p in tool.parameters}
            null_filled.update(params or {})
            rows = session.engine.query(sql, null_filled)
            return {"rows": rows, "row_count": len(rows)}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("tool.preview.failed", tool_id=tool_id, error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))
