"""Studio integration tools — exclusively for the Elliot Studio UI."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)

AUDIT_PATH = os.environ.get("ELLIOT_AUDIT_LOG", ".elliot/audit.ndjson")


def register_studio_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_session_summary() -> dict:  # type: ignore[type-arg]
        """Return a summary of the current session: sources, tools, skills, and context."""
        return {
            "sources": len(session.sources),
            "tools": len(session.registry.get_all()),
            "skills": len(session.registry.get_all_skills()),
            "product_context": (session.product_context.name if session.product_context else None),
        }

    @mcp.tool()
    def studio_get_connector_info() -> dict:  # type: ignore[type-arg]
        """Return the current connector config and session summary (Studio only)."""
        try:
            log.info("studio.connector_info.start")
            result: dict[str, Any] = {
                "source_count": len(session.sources),
                "tool_count": len(session.registry.get_all()),
                "skill_count": len(session.registry.get_all_skills()),
                "product_context": (
                    session.product_context.model_dump() if session.product_context else None
                ),
                "connector_built": session.connector is not None,
            }
            if session.connector:
                result["connector"] = session.connector.model_dump()
            return result
        except Exception as exc:
            log.error("studio.connector_info.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def studio_get_audit_log(limit: int = 50) -> list:  # type: ignore[type-arg]
        """Return the last N audit log entries (Studio only)."""
        try:
            log.info("studio.audit_log.start", limit=limit)
            path = Path(AUDIT_PATH)
            if not path.exists():
                return []
            lines = path.read_text(encoding="utf-8").splitlines()
            tail = [ln for ln in lines[-limit:] if ln.strip()]
            return [json.loads(line) for line in tail]
        except Exception as exc:
            log.error("studio.audit_log.failed", error=str(exc), exc_info=True)
            return []

    @mcp.tool()
    def studio_get_metrics(days: int = 30) -> dict:  # type: ignore[type-arg]
        """Return aggregated tool call metrics (Studio only)."""
        try:
            import time as _time

            log.info("studio.metrics.start", days=days)
            path = Path(AUDIT_PATH)
            if not path.exists():
                return {"metrics": []}

            cutoff = _time.time() - days * 86400
            lines = path.read_text(encoding="utf-8").splitlines()
            call_count: dict[str, int] = defaultdict(int)
            error_count: dict[str, int] = defaultdict(int)
            total_ms: dict[str, float] = defaultdict(float)

            for line in lines:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("ts", 0) < cutoff:
                    continue
                tid = entry.get("tool_id", "unknown")
                call_count[tid] += 1
                if entry.get("error"):
                    error_count[tid] += 1
                total_ms[tid] += entry.get("duration_ms", 0)

            metrics = []
            for tool_id, count in call_count.items():
                errors = error_count.get(tool_id, 0)
                metrics.append(
                    {
                        "tool_id": tool_id,
                        "call_count": count,
                        "error_rate": round(errors / count, 3) if count > 0 else 0,
                        "avg_latency_ms": round(total_ms[tool_id] / count, 2) if count > 0 else 0,
                    }
                )
            metrics.sort(key=lambda x: x.get("call_count") or 0, reverse=True)  # type: ignore[arg-type,return-value]
            return {"metrics": metrics, "days": days}
        except Exception as exc:
            log.error("studio.metrics.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def studio_run_sql(sql: str) -> dict:  # type: ignore[type-arg]
        """Run a raw SELECT against the in-memory SQLite engine (Studio debug only)."""
        from elliot_core.sqlite.query_runner import validate_tool_sql

        try:
            log.info("studio.run_sql.start")
            # validate_tool_sql strips line+block comments, rejects multiple
            # statements, blocks DDL/DML/ATTACH/PRAGMA, and verifies the
            # query begins with SELECT or WITH. The old startswith("SELECT")
            # check was bypassable via leading comments and ATTACH chains.
            ok, reason = validate_tool_sql(sql)
            if not ok:
                raise ElliotError("VALIDATION_ERROR", reason)
            rows = session.engine.query(sql)
            return {"rows": rows, "row_count": len(rows)}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("studio.run_sql.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("SQL_ERROR", str(exc)))
