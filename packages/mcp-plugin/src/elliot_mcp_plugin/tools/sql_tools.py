"""SQL query tools — run ad-hoc queries on loaded SQLite data."""

from __future__ import annotations

import os

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.errors import ElliotError
from elliot_core.sql import safe_ident
from elliot_core.sqlite.query_runner import run_tool_query, validate_tool_sql
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)

# Mirror elliot_connector_runtime.executor.max_result_rows so the ad-hoc SQL
# escape hatch honours the same ELLIOT_MAX_RESULT_ROWS cap as registered tool
# execution (principle #2: results are sized for the context window). Kept local
# rather than imported so mcp-plugin keeps depending only on elliot-core.
_DEFAULT_MAX_RESULT_ROWS = 10_000


def _max_result_rows() -> int:
    raw = os.environ.get("ELLIOT_MAX_RESULT_ROWS", "")
    try:
        return max(1, int(raw)) if raw else _DEFAULT_MAX_RESULT_ROWS
    except ValueError:
        return _DEFAULT_MAX_RESULT_ROWS


def register_sql_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_get_schema() -> dict:  # type: ignore[type-arg]
        """Return all table names and their column definitions."""
        try:
            tables = session.engine.get_table_names()
            return {t: session.engine.get_table_schema(t) for t in tables}
        except ElliotError:
            raise
        except Exception as exc:
            log.error("sql.schema.failed", error=str(exc), exc_info=True)
            raise ElliotError("INTERNAL_ERROR", str(exc)) from exc

    @mcp.tool()
    def elliot_query_sql(sql: str, params: dict | None = None) -> dict:  # type: ignore[type-arg]
        """Run a validated SELECT query against in-memory SQLite. Returns rows and meta.

        Results are capped at ELLIOT_MAX_RESULT_ROWS (default 10,000); when the
        cap is hit the response sets ``truncated: true`` so the agent knows the
        set is incomplete and should narrow the query.
        """
        try:
            rows = run_tool_query(session.engine, sql, params)
            cap = _max_result_rows()
            truncated = len(rows) > cap
            capped = rows[:cap]
            return {"rows": capped, "row_count": len(capped), "truncated": truncated}
        except ElliotError:
            # Raise so FastMCP marks the result isError=true (a returned error
            # dict was treated as a successful, doubly-nested result before).
            raise
        except Exception as exc:
            log.error("sql.query.failed", error=str(exc), exc_info=True)
            raise ElliotError("INTERNAL_ERROR", str(exc)) from exc

    @mcp.tool()
    def elliot_list_tables() -> dict:  # type: ignore[type-arg]
        """List all SQLite tables currently loaded in the session engine."""
        try:
            tables = session.engine.get_table_names()
            return {"tables": tables}
        except ElliotError:
            raise
        except Exception as exc:
            log.error("sql.list_tables.failed", error=str(exc), exc_info=True)
            raise ElliotError("INTERNAL_ERROR", str(exc)) from exc

    @mcp.tool()
    def elliot_sample_data(table_name: str, limit: int = 10) -> dict:  # type: ignore[type-arg]
        """Return N random rows from a table."""
        try:
            # safe_ident validates table_name against ^[A-Za-z_][A-Za-z0-9_]*$
            # and quotes it — a hand-rolled f-string quote would let a name
            # containing a double-quote break out of the identifier.
            rows = session.engine.query(
                f"SELECT * FROM {safe_ident(table_name)} ORDER BY RANDOM() LIMIT :n", {"n": limit}
            )
            return {"rows": rows}
        except ElliotError:
            raise
        except Exception as exc:
            log.error("sql.sample.failed", error=str(exc), exc_info=True)
            raise ElliotError("INTERNAL_ERROR", str(exc)) from exc

    @mcp.tool()
    def elliot_profile_column(table_name: str, column_name: str) -> dict:  # type: ignore[type-arg]
        """Return min, max, null count, distinct count, and top 5 values for a column."""
        try:
            return session.engine.profile_column(table_name, column_name)
        except ElliotError:
            raise
        except Exception as exc:
            log.error("sql.profile.failed", error=str(exc), exc_info=True)
            raise ElliotError("INTERNAL_ERROR", str(exc)) from exc

    @mcp.tool()
    def elliot_validate_sql(sql: str) -> dict:  # type: ignore[type-arg]
        """Validate a SQL query without executing it. Returns valid/invalid and reason."""
        try:
            valid, reason = validate_tool_sql(sql)
            return {"valid": valid, "reason": reason}
        except ElliotError:
            raise
        except Exception as exc:
            log.error("sql.validate.failed", error=str(exc), exc_info=True)
            raise ElliotError("INTERNAL_ERROR", str(exc)) from exc

    @mcp.tool()
    def elliot_explain_query(sql: str) -> dict:  # type: ignore[type-arg]
        """Return EXPLAIN QUERY PLAN output for a SELECT statement."""
        try:
            # Reject non-SELECT statements before planning them — keep the same
            # read-only trust boundary as elliot_query_sql rather than passing
            # arbitrary SQL straight through.
            valid, reason = validate_tool_sql(sql)
            if not valid:
                raise ElliotError("INVALID_SQL", reason)
            rows = session.engine.query(f"EXPLAIN QUERY PLAN {sql}")
            return {"plan": rows}
        except ElliotError:
            raise
        except Exception as exc:
            log.error("sql.explain.failed", error=str(exc), exc_info=True)
            raise ElliotError("INTERNAL_ERROR", str(exc)) from exc
