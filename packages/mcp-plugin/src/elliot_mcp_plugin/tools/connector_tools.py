"""Connector build tools — assemble, export, and manage the connector runtime."""

from __future__ import annotations

import subprocess
from pathlib import Path

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.connector.serializer import serialize_connector
from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)


def register_connector_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_build_connector(
        name: str,
        slug: str,
        version: str | None = None,
        description: str = "",
        tool_ids: list[str] | None = None,
        skill_ids: list[str] | None = None,
    ) -> dict:  # type: ignore[type-arg]
        """Assemble a ConnectorConfig from selected (or all) tools and skills."""
        try:
            effective_version = (
                version or (session.connector.version if session.connector else None) or "1.0.0"
            )
            selected_tools = (
                [t for t in session.registry.get_all() if t.id in tool_ids]
                if tool_ids is not None
                else session.registry.get_all()
            )
            selected_skills = (
                [s for s in session.registry.get_all_skills() if s.id in (skill_ids or [])]
                if skill_ids is not None
                else session.registry.get_all_skills()
            )
            referenced_source_ids = {sid for t in selected_tools for sid in t.source_ids}
            sources = [s for sid, s in session.sources.items() if sid in referenced_source_ids]

            # GAP-2: inject SQL that was stored separately back into ToolDefinition objects
            tools_with_sql = []
            for tool in selected_tools:
                sql = session.tool_sql.get(tool.id)
                if sql:
                    tool = tool.model_copy(update={"sql": sql})
                tools_with_sql.append(tool)

            # GAP-3: replace UUID source IDs with human-readable source names
            uuid_to_name = {sid: src.name for sid, src in session.sources.items()}
            sources_named = [src.model_copy(update={"id": src.name}) for src in sources]
            tools_remapped = [
                tool.model_copy(
                    update={"source_ids": [uuid_to_name.get(sid, sid) for sid in tool.source_ids]}
                )
                for tool in tools_with_sql
            ]

            config = session.builder.set_meta(
                name=name, slug=slug, version=effective_version, description=description
            ).build(sources=sources_named, tools=tools_remapped, skills=selected_skills)

            session.connector = config
            log.info(
                "connector.built",
                name=name,
                tools=len(selected_tools),
                skills=len(selected_skills),
            )
            return {
                "status": "built",
                "tool_count": len(selected_tools),
                "skill_count": len(selected_skills),
                "source_count": len(sources),
            }
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("connector.build.failed", error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_export_connector(path: str = ".elliot/connector.json") -> dict:  # type: ignore[type-arg]
        """Write the built ConnectorConfig to disk as JSON."""
        try:
            if session.connector is None:
                return {"error": "No connector built yet — call elliot_build_connector first"}
            dest = Path(path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(serialize_connector(session.connector))
            log.info("connector.exported", path=str(dest))

            # Staleness check: warn if tools or SQL changed since last build
            stale_warnings: list[str] = []
            built_ids = {t.id for t in session.connector.tools}
            current_ids = {t.id for t in session.registry.get_all()}
            added = current_ids - built_ids
            removed = built_ids - current_ids
            if added:
                stale_warnings.append(f"New tools not in connector: {', '.join(sorted(added))}")
            if removed:
                stale_warnings.append(f"Tools removed since build: {', '.join(sorted(removed))}")
            for t in session.connector.tools:
                current_sql = session.tool_sql.get(t.id)
                if current_sql and current_sql != t.sql:
                    stale_warnings.append(
                        f"Tool '{t.id}' SQL changed since last build — rebuild recommended"
                    )

            result: dict[str, object] = {"status": "exported", "path": str(dest)}
            if stale_warnings:
                result["warnings"] = stale_warnings
            return result
        except Exception as exc:
            log.error("connector.export.failed", error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_save_session() -> dict:  # type: ignore[type-arg]
        """Persist the current session state to .elliot/session.json."""
        try:
            session.save()
            session_path = str(session.workspace._dir / "session.json")
            return {"status": "ok", "path": session_path}
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_lint_connector() -> dict:  # type: ignore[type-arg]
        """Run the static linter on the current built connector and return all issues."""
        try:
            import dataclasses

            from elliot_core.linter import lint_connector

            if session.connector is None:
                return {"error": "No connector built yet — call elliot_build_connector first"}
            issues = lint_connector(session.connector)
            return {
                "issues": [dataclasses.asdict(i) for i in issues],
                "error_count": sum(1 for i in issues if i.severity == "ERROR"),
                "warning_count": sum(1 for i in issues if i.severity == "WARN"),
            }
        except Exception as exc:
            log.error("connector.lint.failed", error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_start_runtime(port: int = 3001) -> dict:  # type: ignore[type-arg]
        """Start the connector runtime as a subprocess on the given port."""
        try:
            if session.runtime_process and session.runtime_process.poll() is None:
                return {"status": "already_running", "pid": session.runtime_process.pid}
            session.runtime_process = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "uvicorn",
                    "elliot_connector_runtime.server:app",
                    f"--port={port}",
                    "--app-dir=packages/connector-runtime/src",
                ]
            )
            log.info("runtime.started", port=port, pid=session.runtime_process.pid)
            return {"url": f"http://localhost:{port}/mcp", "pid": session.runtime_process.pid}
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_stop_runtime() -> dict:  # type: ignore[type-arg]
        """Stop the running connector runtime process."""
        try:
            if session.runtime_process is None:
                return {"status": "not_running"}
            session.runtime_process.terminate()
            session.runtime_process = None
            log.info("runtime.stopped")
            return {"status": "stopped"}
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_get_connection_config() -> dict:  # type: ignore[type-arg]
        """Return the MCP config snippet to add to an agent's config."""
        return {"type": "http", "url": "http://localhost:3001/mcp"}
