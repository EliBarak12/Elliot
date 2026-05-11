"""Source management tools — discover, preview, profile and manage data sources."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.sources.api_fetcher import fetch_endpoint
from elliot_core.sources.db_connector import query_database
from elliot_core.sources.file_reader import read_file
from elliot_core.sqlite.flattener import flatten
from elliot_core.types.source import SourceConfig
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)

# Maps the agent-friendly source_type to the SourceConfig Literal
_TYPE_MAP: dict[str, str] = {
    "api": "rest",
    "file": "file",
    "db": "postgres",
}


def _build_source_config(
    source_type: str, config: dict[str, Any], source_id: str, name: str
) -> SourceConfig:
    """Validate a raw config dict into a SourceConfig, mapping friendly types."""
    mapped_type = _TYPE_MAP.get(source_type, source_type)
    merged = {"id": source_id, "type": mapped_type, "name": name, **config}
    return SourceConfig.model_validate(merged)


def register_source_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    async def elliot_discover_source(
        source_type: str,
        config: dict,  # type: ignore[type-arg]
        name: str,
    ) -> dict:  # type: ignore[type-arg]
        """Fetch a data source (API / file / DB) and load it into in-memory SQLite.

        source_type: 'api' | 'file' | 'db'
        config: source-specific config dict (url, path, table, auth, etc.)
        name: logical name used as the SQLite table prefix
        """
        try:
            if source_type not in ("api", "file", "db"):
                return {
                    "error": f"Unknown source_type: {source_type!r}. Use 'api', 'file', or 'db'"
                }

            source_id = str(uuid.uuid4())
            cfg = _build_source_config(source_type, config, source_id, name)
            secrets = session.workspace.load_secrets()

            rows: list[dict[str, Any]]
            if source_type == "file":
                result = read_file(cfg)
                rows = result.rows

            elif source_type == "api":
                result = await fetch_endpoint(cfg, secrets)
                rows = result.rows

            else:  # db
                result = query_database(cfg, secrets)
                rows = result.rows

            flat = flatten(rows, table_name=name)
            session.engine.load_result(flat)

            cfg.table_name = name
            cfg.row_count = len(rows)
            cfg.config_snapshot = config
            session.sources[source_id] = cfg
            session.save()

            log.info(
                "source.discovered",
                source_id=source_id,
                table=name,
                rows=len(rows),
            )
            return {
                "source_id": source_id,
                "table_name": name,
                "row_count": len(rows),
                "columns": [c.name for c in flat.primary_table.columns],
                "warnings": flat.warnings,
            }

        except ElliotError as exc:
            log.error("source.discover.failed", error=exc.message)
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("source.discover.failed", error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_list_sources() -> dict:  # type: ignore[type-arg]
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
            log.error("source.list.failed", error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_preview_source(table_name: str, limit: int = 10) -> dict:  # type: ignore[type-arg]
        """Return the first N rows from a loaded source table."""
        try:
            rows = session.engine.query(f'SELECT * FROM "{table_name}" LIMIT :n', {"n": limit})
            schema = session.engine.get_table_schema(table_name)
            return {"rows": rows, "row_count": len(rows), "schema": schema}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            return {"error": f"Table '{table_name}' not found or query failed: {exc}"}

    @mcp.tool()
    def elliot_profile_source(table_name: str) -> dict:  # type: ignore[type-arg]
        """Return column statistics (min, max, nulls, distinct, top values) for a table."""
        try:
            schema = session.engine.get_table_schema(table_name)
            stats = session.engine.get_table_stats(table_name)
            profiles = {
                col["name"]: session.engine.profile_column(table_name, col["name"])
                for col in schema
            }
            return {
                "table": table_name,
                "row_count": stats["row_count"],
                "columns": profiles,
            }
        except Exception as exc:
            log.error("source.profile.failed", table=table_name, error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    async def elliot_refresh_source(source_id: str) -> dict:  # type: ignore[type-arg]
        """Re-fetch a source from its origin and reload the table in SQLite."""
        try:
            src = session.sources.get(source_id)
            if src is None:
                return {"error": f"Source not found: {source_id}"}
            # Map SourceConfig.type back to friendly type
            reverse_map = {v: k for k, v in _TYPE_MAP.items()}
            friendly_type = reverse_map.get(src.type, src.type)
            return await elliot_discover_source(
                source_type=friendly_type,
                config=src.config_snapshot or {},
                name=src.name,
            )
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_remove_source(source_id: str) -> dict:  # type: ignore[type-arg]
        """Remove a source and drop its table from in-memory SQLite."""
        try:
            src = session.sources.pop(source_id, None)
            if src is None:
                return {"error": f"Source not found: {source_id}"}
            if src.table_name:
                session.engine._conn.execute(f'DROP TABLE IF EXISTS "{src.table_name}"')
                session.engine._conn.commit()
            session.save()
            log.info("source.removed", source_id=source_id, table=src.table_name)
            return {"status": "removed", "source_id": source_id, "table": src.table_name}
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))
