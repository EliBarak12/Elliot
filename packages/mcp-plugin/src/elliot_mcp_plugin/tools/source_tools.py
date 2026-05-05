"""Source management tools — discover and inspect data sources."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession


def register_source_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_discover_source(
        source_type: str,
        url: str,
        name: str,
        auth_type: str = "none",
        auth_secret_key: str = "",
    ) -> dict:  # type: ignore[type-arg]
        """Fetch a data source and register it in the current session."""
        from elliot_core.errors import ElliotError

        try:
            from elliot_core.types.source import AuthConfig, SourceConfig

            source_id = name.lower().replace(" ", "_")
            auth = (
                AuthConfig.model_validate({"type": auth_type, "secret_key": auth_secret_key})
                if auth_type != "none"
                else None
            )
            source = SourceConfig.model_validate(
                {"id": source_id, "name": name, "type": source_type, "url": url, "auth": auth}
            )
            session.sources[source_id] = source
            return {"status": "ok", "source_id": source_id}
        except ElliotError as exc:
            return {"error": f"[{exc.code}] {exc.message}"}

    @mcp.tool()
    def elliot_list_sources() -> dict:  # type: ignore[type-arg]
        """List all registered data sources in the current session."""
        return {
            "sources": [
                {"id": s.id, "name": s.name, "type": s.type, "url": s.url}
                for s in session.sources.values()
            ]
        }
