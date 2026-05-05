"""Context tools — set and inspect the product context for the session."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession


def register_context_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_set_context(
        name: str,
        description: str = "",
        base_url: str = "",
        version: str = "",
    ) -> dict:  # type: ignore[type-arg]
        """Set the product context (name, description, base URL) for the current session."""
        from elliot_core.types.connector import ProductContext

        session.product_context = ProductContext(
            name=name, description=description, base_url=base_url, version=version
        )
        return {"status": "ok", "context": session.product_context.model_dump()}

    @mcp.tool()
    def elliot_get_context() -> dict:  # type: ignore[type-arg]
        """Return the current product context for this session."""
        if not session.product_context:
            return {"context": None}
        return {"context": session.product_context.model_dump()}
