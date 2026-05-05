"""Connector build tools — serialize and export a full ConnectorConfig."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession


def register_connector_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_build_connector(
        name: str,
        slug: str,
        version: str = "1.0.0",
        description: str = "",
    ) -> dict:  # type: ignore[type-arg]
        """Build a ConnectorConfig from the current session state and return it as JSON."""
        from elliot_core.connector.serializer import serialize_connector
        from elliot_core.errors import ElliotError

        try:
            config = session.builder.set_meta(
                name=name, slug=slug, version=version, description=description
            ).build(
                sources=list(session.sources.values()),
                tools=session.registry.get_all(),
                skills=session.registry.get_all_skills(),
            )
            return {"status": "ok", "connector_json": serialize_connector(config)}
        except ElliotError as exc:
            return {"error": f"[{exc.code}] {exc.message}"}

    @mcp.tool()
    def elliot_save_session() -> dict:  # type: ignore[type-arg]
        """Persist the current session state to .elliot/session.json."""
        try:
            session.save()
            return {"status": "ok"}
        except Exception as exc:
            return {"error": str(exc)}
