"""Connector build tools — assemble, export, and manage the connector runtime."""

from __future__ import annotations

import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.connector.serializer import serialize_connector
from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)

_RUNTIME_LOG_RELATIVE = Path(".elliot/runtime.log")
_RUNTIME_HEALTH_TIMEOUT_S = 15.0
_RUNTIME_HEALTH_INTERVAL_S = 0.2
_LOG_TAIL_BYTES = 4096


def _tail_log(log_path: Path, n_bytes: int = _LOG_TAIL_BYTES) -> str:
    if not log_path.exists():
        return ""
    try:
        with log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - n_bytes))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _wait_for_runtime(
    process: subprocess.Popen[bytes],
    health_url: str,
    deadline: float,
) -> tuple[bool, str | None]:
    """Poll /health until the process answers, dies, or we time out.

    Returns (ok, reason). `ok=True` means we got an HTTP response from /health.
    `ok=False` carries a short reason: process crashed, timeout, or HTTP error.
    """
    while time.monotonic() < deadline:
        rc = process.poll()
        if rc is not None:
            return False, f"runtime process exited with code {rc}"
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True, None
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(_RUNTIME_HEALTH_INTERVAL_S)
    return False, f"timeout after {_RUNTIME_HEALTH_TIMEOUT_S}s waiting for /health"


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
    def elliot_start_runtime(
        port: int = 3001,
        connector_path: str | None = None,
    ) -> dict:  # type: ignore[type-arg]
        """Start the connector runtime as a subprocess and wait until /health is alive.

        Captures the subprocess stdout+stderr to .elliot/runtime.log. Only returns
        success once the runtime answers /health (or returns a failure with a tail
        of the log if the process crashes or times out).

        `connector_path` defaults to the most recently exported connector, then to
        the ELLIOT_CONNECTOR env var, then `.elliot/connector.json`. Passing it
        explicitly is how an agent says "serve THIS connector to clients".
        """
        try:
            if session.runtime_process and session.runtime_process.poll() is None:
                return {
                    "status": "already_running",
                    "pid": session.runtime_process.pid,
                    "url": f"http://localhost:{port}/mcp/",
                }

            workspace_dir = Path(session.workspace._dir)
            log_path = workspace_dir / "runtime.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)

            chosen_connector = (
                connector_path
                or os.environ.get("ELLIOT_CONNECTOR")
                or str(workspace_dir / "connector.json")
            )
            if not Path(chosen_connector).exists():
                return to_mcp_error_content(
                    ElliotError(
                        "RUNTIME_NO_CONNECTOR",
                        (
                            f"Connector file not found at '{chosen_connector}'. "
                            "Run elliot_build_connector + elliot_export_connector first, "
                            "or pass connector_path to elliot_start_runtime."
                        ),
                        detail={"connector_path": chosen_connector},
                    )
                )

            env = os.environ.copy()
            env["ELLIOT_CONNECTOR"] = chosen_connector

            log_fh = log_path.open("wb")
            try:
                proc = subprocess.Popen(
                    [
                        "uv",
                        "run",
                        "uvicorn",
                        "elliot_connector_runtime.server:app",
                        f"--port={port}",
                        "--app-dir=packages/connector-runtime/src",
                    ],
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    env=env,
                )
            finally:
                # The subprocess inherits the fd; we can safely close our handle.
                log_fh.close()

            session.runtime_process = proc
            session.runtime_log_path = log_path

            deadline = time.monotonic() + _RUNTIME_HEALTH_TIMEOUT_S
            ok, reason = _wait_for_runtime(proc, f"http://localhost:{port}/health", deadline)
            if not ok:
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        proc.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                session.runtime_process = None
                log.error("runtime.start.failed", port=port, reason=reason)
                return to_mcp_error_content(
                    ElliotError(
                        "RUNTIME_START_FAILED",
                        f"Runtime did not become healthy: {reason}",
                        detail={
                            "log_tail": _tail_log(log_path),
                            "log_path": str(log_path),
                            "exit_code": proc.poll(),
                        },
                    )
                )

            log.info("runtime.started", port=port, pid=proc.pid, connector=chosen_connector)
            return {
                "status": "running",
                "url": f"http://localhost:{port}/mcp/",
                "pid": proc.pid,
                "connector_path": chosen_connector,
                "log_path": str(log_path),
            }
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_stop_runtime() -> dict:  # type: ignore[type-arg]
        """Stop the running connector runtime process."""
        try:
            if session.runtime_process is None:
                return {"status": "not_running"}
            session.runtime_process.terminate()
            try:
                session.runtime_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                session.runtime_process.kill()
            session.runtime_process = None
            log.info("runtime.stopped")
            return {"status": "stopped"}
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_runtime_logs(n_bytes: int = _LOG_TAIL_BYTES) -> dict:  # type: ignore[type-arg]
        """Return the tail of the connector-runtime log captured by elliot_start_runtime."""
        log_path = session.runtime_log_path or (Path(session.workspace._dir) / "runtime.log")
        try:
            if not log_path.exists():
                return {
                    "log_path": str(log_path),
                    "exists": False,
                    "tail": "",
                    "note": "No runtime log yet — start the runtime first.",
                }
            return {
                "log_path": str(log_path),
                "exists": True,
                "tail": _tail_log(log_path, n_bytes),
            }
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_get_connection_config(port: int = 3001) -> dict:  # type: ignore[type-arg]
        """Return the MCP config snippet to add to an agent's config.

        The URL includes a trailing slash because FastMCP's streamable_http
        endpoint is mounted on a path-prefix; some MCP clients (Codex/rmcp)
        do not follow the 307 redirect FastAPI emits for the slash-less form.
        """
        return {"type": "http", "url": f"http://localhost:{port}/mcp/"}
