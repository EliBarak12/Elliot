"""Studio integration tools — expose session state to the Studio UI."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession


def register_studio_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_session_summary() -> dict:  # type: ignore[type-arg]
        """Return a summary of the current session: sources, tools, skills, and context."""
        return {
            "sources": len(session.sources),
            "tools": len(session.registry.get_all()),
            "skills": len(session.registry.get_all_skills()),
            "product_context": (session.product_context.name if session.product_context else None),
        }
