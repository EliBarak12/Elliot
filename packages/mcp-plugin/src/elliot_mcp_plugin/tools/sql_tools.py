"""SQL query tools — run ad-hoc queries on loaded SQLite data."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession


def register_sql_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_query_sql(sql: str, source_id: str) -> dict:  # type: ignore[type-arg]
        """Run a SELECT query against an in-memory SQLite table loaded from a source."""
        from elliot_core.errors import ElliotError

        try:
            rows = session.engine.query(sql, {})
            return {"rows": rows, "row_count": len(rows)}
        except ElliotError as exc:
            return {"error": f"[{exc.code}] {exc.message}"}
        except Exception as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def elliot_list_tables() -> dict:  # type: ignore[type-arg]
        """List all SQLite tables currently loaded in the session engine."""
        try:
            rows = session.engine.query(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name", {}
            )
            return {"tables": [r["name"] for r in rows]}
        except Exception as exc:
            return {"error": str(exc)}
