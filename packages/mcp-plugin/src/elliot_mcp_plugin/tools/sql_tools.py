"""SQL query tools — run ad-hoc queries on loaded SQLite data."""

from __future__ import annotations

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.sqlite.query_runner import run_tool_query, validate_tool_sql
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)


def register_sql_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_get_schema() -> dict:  # type: ignore[type-arg]
        """Return all table names and their column definitions."""
        try:
            tables = session.engine.get_table_names()
            return {t: session.engine.get_table_schema(t) for t in tables}
        except Exception as exc:
            log.error("sql.schema.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_query_sql(sql: str, params: dict | None = None) -> dict:  # type: ignore[type-arg]
        """Run a validated SELECT query against in-memory SQLite. Returns rows and meta."""
        try:
            rows = run_tool_query(session.engine, sql, params)
            return {"rows": rows, "row_count": len(rows)}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("sql.query.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_list_tables() -> dict:  # type: ignore[type-arg]
        """List all SQLite tables currently loaded in the session engine."""
        try:
            tables = session.engine.get_table_names()
            return {"tables": tables}
        except Exception as exc:
            log.error("sql.list_tables.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_sample_data(table_name: str, limit: int = 10) -> dict:  # type: ignore[type-arg]
        """Return N random rows from a table."""
        try:
            rows = session.engine.query(
                f'SELECT * FROM "{table_name}" ORDER BY RANDOM() LIMIT :n', {"n": limit}
            )
            return {"rows": rows}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("sql.sample.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_profile_column(table_name: str, column_name: str) -> dict:  # type: ignore[type-arg]
        """Return min, max, null count, distinct count, and top 5 values for a column."""
        try:
            return session.engine.profile_column(table_name, column_name)
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("sql.profile.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_validate_sql(sql: str) -> dict:  # type: ignore[type-arg]
        """Validate a SQL query without executing it. Returns valid/invalid and reason."""
        try:
            valid, reason = validate_tool_sql(sql)
            return {"valid": valid, "reason": reason}
        except Exception as exc:
            log.error("sql.validate.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_explain_query(sql: str) -> dict:  # type: ignore[type-arg]
        """Return EXPLAIN QUERY PLAN output for a SELECT statement."""
        try:
            rows = session.engine.query(f"EXPLAIN QUERY PLAN {sql}")
            return {"plan": rows}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("sql.explain.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))
