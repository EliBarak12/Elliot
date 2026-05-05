# 024 — Source MCP Tools

**Sprint**: 2 | **Estimate**: 3h | **Depends on**: 023

## Files to Create

### `packages/mcp-plugin/src/elliot_mcp_plugin/tools/source_tools.py`

```python
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.sources.api_fetcher import fetch_endpoint
from elliot_core.sources.db_connector import query_database
from elliot_core.sources.file_reader import read_file
from elliot_core.sqlite.flattener import flatten
from elliot_core.types.source import ApiEndpointConfig, DbSourceConfig, FileSourceConfig
from elliot_mcp_plugin.session import ElliotSession


def register_source_tools(mcp: FastMCP, session: ElliotSession) -> None:

    @mcp.tool()
    def elliot_discover_source(
        source_type: str,
        config: dict,
        name: str,
    ) -> dict:
        """Fetch a data source (API / file / DB) and load it into in-memory SQLite.

        source_type: 'api' | 'file' | 'db'
        config: source-specific config dict (see SourceConfig types)
        name: logical name used as the SQLite table prefix
        """
        try:
            rows: list[dict[str, Any]]

            if source_type == "file":
                cfg = FileSourceConfig.model_validate(config)
                rows = read_file(cfg)

            elif source_type == "api":
                cfg = ApiEndpointConfig.model_validate(config)
                secrets = session.workspace.load_secrets()
                result = asyncio.run(fetch_endpoint(cfg, secrets))
                rows = result.rows

            elif source_type == "db":
                cfg = DbSourceConfig.model_validate(config)
                secrets = session.workspace.load_secrets()
                fetch_result = query_database(cfg, secrets)
                rows = fetch_result.rows

            else:
                return {"error": f"Unknown source_type: {source_type!r}. Use 'api', 'file', or 'db'"}

            flat = flatten(rows, table_name=name)
            session.engine.load_result(flat)

            source_id = str(uuid.uuid4())
            from elliot_core.types.source import SourceConfig
            session.sources[source_id] = SourceConfig(
                id=source_id,
                name=name,
                type=source_type,
                table_name=name,
                row_count=len(rows),
            )
            session.save()

            return {
                "source_id": source_id,
                "table_name": name,
                "row_count": len(rows),
                "columns": [c.name for c in flat.primary_table.columns],
                "warnings": flat.warnings,
            }

        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            return to_mcp_error_content(exc)

    @mcp.tool()
    def elliot_list_sources() -> dict:
        """List all loaded sources with their table names and row counts."""
        try:
            return {
                "sources": [
                    {
                        "source_id": sid,
                        "name": src.name,
                        "type": src.type,
                        "table_name": src.table_name,
                        "row_count": src.row_count,
                    }
                    for sid, src in session.sources.items()
                ],
                "count": len(session.sources),
            }
        except Exception as exc:
            return to_mcp_error_content(exc)

    @mcp.tool()
    def elliot_preview_source(table_name: str, limit: int = 10) -> dict:
        """Return the first N rows from a loaded source table."""
        try:
            rows = session.engine.query(
                f'SELECT * FROM "{table_name}" LIMIT :n', {"n": limit}
            )
            schema = session.engine.get_table_schema(table_name)
            return {"rows": rows, "row_count": len(rows), "schema": schema}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            return {"error": f"Table '{table_name}' not found or query failed: {exc}"}

    @mcp.tool()
    def elliot_profile_source(table_name: str) -> dict:
        """Return column statistics (min, max, nulls, distinct, top values) for a table."""
        try:
            schema = session.engine.get_table_schema(table_name)
            stats = session.engine.get_table_stats(table_name)
            profiles = {
                col["name"]: session.engine.profile_column(table_name, col["name"])
                for col in schema
            }
            return {"table": table_name, "row_count": stats["row_count"], "columns": profiles}
        except Exception as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def elliot_refresh_source(source_id: str) -> dict:
        """Re-fetch a source from its origin and reload the table in SQLite."""
        try:
            src = session.sources.get(source_id)
            if src is None:
                return {"error": f"Source not found: {source_id}"}
            # Re-discover with same config
            return elliot_discover_source(
                source_type=src.type,
                config=src.config_snapshot or {},
                name=src.name,
            )
        except Exception as exc:
            return to_mcp_error_content(exc)

    @mcp.tool()
    def elliot_remove_source(source_id: str) -> dict:
        """Remove a source and drop its table from in-memory SQLite."""
        try:
            src = session.sources.pop(source_id, None)
            if src is None:
                return {"error": f"Source not found: {source_id}"}
            session.engine._conn.execute(f'DROP TABLE IF EXISTS "{src.table_name}"')
            session.engine._conn.commit()
            session.save()
            return {"status": "removed", "source_id": source_id, "table": src.table_name}
        except Exception as exc:
            return to_mcp_error_content(exc)
```

## Done When
- [ ] `elliot_discover_source` with CSV fixture returns `{source_id, row_count, columns}`
- [ ] `elliot_list_sources` returns count matching discovered sources
- [ ] `elliot_preview_source` returns correct rows with schema
- [ ] `elliot_remove_source` drops the table; subsequent list no longer shows it
- [ ] Unknown `source_type` returns `{"error": ...}` (does not raise)
- [ ] All handlers have top-level try/except; no raw exception escapes
