# 024 — Source MCP Tools

**Sprint**: 2 | **Estimate**: 3h | **Depends on**: 023

## Files to Create

### `packages/mcp-plugin/src/elliot_mcp_plugin/tools/source_tools.py`

```python
import uuid, asyncio
from mcp.server.fastmcp import FastMCP
from elliot_mcp_plugin.session import ElliotSession
from elliot_core.sources.api_fetcher import fetch_endpoint
from elliot_core.sources.file_reader import read_file
from elliot_core import flatten, ElliotError

def register_source_tools(mcp: FastMCP, session: ElliotSession) -> None:

    @mcp.tool()
    def elliot_discover_source(source_type: str, config: dict, name: str) -> dict:
        """Fetch a data source (API/file/DB) and load it into in-memory SQLite."""
        try:
            if source_type == "file":
                result = read_file(...)
            elif source_type == "api":
                result = asyncio.run(fetch_endpoint(...))
            flat = flatten(result.rows, name)
            session.engine.load_result(flat)
            source_id = str(uuid.uuid4())
            session.sources[source_id] = ...
            session.save()
            return {"source_id": source_id, "tables": [...], "warnings": [...]}
        except ElliotError as e:
            return {"error": f"[{e.code}] {e.message}"}

    @mcp.tool()
    def elliot_list_sources() -> dict:
        """List all loaded sources with their table names and row counts."""
        ...

    @mcp.tool()
    def elliot_preview_source(table_name: str, limit: int = 10) -> dict:
        """Return the first N rows from a loaded table."""
        ...

    @mcp.tool()
    def elliot_profile_source(table_name: str) -> dict:
        """Return column statistics for all columns in a table."""
        ...

    @mcp.tool()
    def elliot_refresh_source(source_id: str) -> dict:
        """Re-fetch a source and reload its data into SQLite."""
        ...

    @mcp.tool()
    def elliot_remove_source(source_id: str) -> dict:
        """Remove a source and drop its tables from SQLite."""
        ...
```

## Done When
- [ ] `elliot_discover_source` with CSV fixture returns schema
- [ ] `elliot_list_sources` returns count matching discovered sources
- [ ] `elliot_remove_source` drops the table from SQLite
