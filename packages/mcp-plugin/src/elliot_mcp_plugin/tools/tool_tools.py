"""Tool definition management — create, update, delete tools in the registry."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession


def register_tool_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_list_tools() -> dict:  # type: ignore[type-arg]
        """List all tools currently defined in the session registry."""
        return {
            "tools": [
                {"id": t.id, "name": t.name, "category": t.category}
                for t in session.registry.get_all()
            ]
        }

    @mcp.tool()
    def elliot_delete_tool(tool_id: str) -> dict:  # type: ignore[type-arg]
        """Remove a tool from the session registry by ID."""
        from elliot_core.errors import ElliotError

        try:
            session.registry.delete(tool_id)
            return {"status": "ok", "deleted": tool_id}
        except ElliotError as exc:
            return {"error": f"[{exc.code}] {exc.message}"}
