# 025 — SQL MCP Tools

**Sprint**: 2 | **Estimate**: 2h | **Depends on**: 024

## Files to Create

### `packages/mcp-plugin/src/elliot_mcp_plugin/tools/sql_tools.py`

```python
from mcp.server.fastmcp import FastMCP
from elliot_mcp_plugin.session import ElliotSession
from elliot_core.sqlite.query_runner import validate_tool_sql, run_tool_query
from elliot_core import ElliotError

def register_sql_tools(mcp: FastMCP, session: ElliotSession) -> None:

    @mcp.tool()
    def elliot_get_schema() -> dict:
        """Return all table names and their column definitions."""
        tables = session.engine.get_table_names()
        return {t: session.engine.get_table_schema(t) for t in tables}

    @mcp.tool()
    def elliot_query_sql(sql: str, params: dict | None = None) -> dict:
        """Run a validated SELECT query against in-memory SQLite. Returns rows and meta."""
        try:
            rows = run_tool_query(session.engine, sql, params)
            return {"rows": rows, "row_count": len(rows)}
        except ElliotError as e:
            return {"error": f"[{e.code}] {e.message}"}

    @mcp.tool()
    def elliot_sample_data(table_name: str, limit: int = 10) -> dict:
        """Return N random rows from a table."""
        rows = session.engine.query(
            f'SELECT * FROM "{table_name}" ORDER BY RANDOM() LIMIT :n', {"n": limit}
        )
        return {"rows": rows}

    @mcp.tool()
    def elliot_profile_column(table_name: str, column_name: str) -> dict:
        """Return min, max, null count, distinct count, and top 5 values for a column."""
        return session.engine.profile_column(table_name, column_name)

    @mcp.tool()
    def elliot_validate_sql(sql: str) -> dict:
        """Validate a SQL query without executing it. Returns valid/invalid and reason."""
        valid, reason = validate_tool_sql(sql)
        return {"valid": valid, "reason": reason}

    @mcp.tool()
    def elliot_explain_query(sql: str) -> dict:
        """Return EXPLAIN QUERY PLAN output for a SELECT statement."""
        try:
            rows = session.engine.query(f"EXPLAIN QUERY PLAN {sql}")
            return {"plan": rows}
        except Exception as e:
            return {"error": str(e)}
```

## Done When
- [ ] `elliot_query_sql` with valid SELECT returns rows
- [ ] `elliot_query_sql` with DROP returns `{"error": ...}` (not raises)
- [ ] `elliot_validate_sql` correctly classifies valid/invalid
