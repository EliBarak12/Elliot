"""Connector build tools — assemble, export, and manage the connector runtime."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.connector.serializer import serialize_connector
from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.types.tool import ToolDefinition
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)


def _build_table_warnings(
    session: ElliotSession, tools: list[ToolDefinition]
) -> list[dict[str, Any]]:
    """Flag built tools whose SQL references tables not loaded in the session.

    Only checked when the session has data materialized (post-discover) and
    only for SQL-backed tools — filter_groups / passthrough tools resolve
    their tables at runtime. Each entry names the tool and its missing tables
    so the agent can fix or drop it before publishing (audit B3).
    """
    from elliot_core.sql import extract_table_names

    available = set(session.engine.get_table_names())
    if not available:
        return []
    warnings: list[dict[str, Any]] = []
    for tool in tools:
        sql = session.tool_sql.get(tool.id)
        if not sql:
            continue
        missing = [t for t in extract_table_names(sql) if t not in available]
        if missing:
            warnings.append(
                {
                    "tool_id": tool.id,
                    "missing_tables": sorted(missing),
                    "message": (
                        f"Tool '{tool.id}' references table(s) "
                        f"{sorted(missing)} that are not loaded — it will fail at "
                        "call time. Fix its SQL or drop the tool before publishing."
                    ),
                }
            )
    return warnings


_RUNTIME_LOG_RELATIVE = Path(".elliot/runtime.log")
_RUNTIME_HEALTH_TIMEOUT_S = 15.0
_RUNTIME_HEALTH_INTERVAL_S = 0.2
_LOG_TAIL_BYTES = 4096


def _kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    """Terminate the runtime subprocess and every child it spawned."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                check=False,
                capture_output=True,
            )
    else:
        import signal

        with contextlib.suppress(Exception):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    with contextlib.suppress(Exception):
        proc.wait(timeout=5)
    if proc.poll() is None:
        # Still alive — escalate to SIGKILL of the group / hard kill.
        if sys.platform != "win32":
            import signal

            with contextlib.suppress(Exception):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            with contextlib.suppress(Exception):
                proc.kill()
        with contextlib.suppress(Exception):
            proc.wait(timeout=3)


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
        instructions: str = "",
        tool_ids: list[str] | None = None,
        skill_ids: list[str] | None = None,
    ) -> dict:  # type: ignore[type-arg]
        """Assemble a ConnectorConfig from selected (or all) tools and skills.

        ``instructions`` is connector-level guidance the agent authors for this
        connector — the same role Elliot's own ``instructions`` play for the
        platform. The connector runtime surfaces it to any MCP client on the
        ``initialize`` handshake (and it is shown to the connector's owner in
        the Studio / cloud UI), so use it to tell downstream agents how to use
        these tools: auth quirks, pagination defaults, which tool to reach for
        first. Leave empty to fall back to an auto-generated description.
        """
        try:
            effective_version = (
                version or (session.connector.version if session.connector else None) or "1.0.0"
            )
            # Preserve previously-authored instructions across a rebuild that
            # omits them, mirroring how version is carried forward.
            effective_instructions = instructions or (
                session.connector.instructions if session.connector else ""
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
                name=name,
                slug=slug,
                version=effective_version,
                description=description,
                instructions=effective_instructions,
            ).build(sources=sources_named, tools=tools_remapped, skills=selected_skills)

            session.connector = config
            log.info(
                "connector.built",
                name=name,
                tools=len(selected_tools),
                skills=len(selected_skills),
            )
            result = {
                "status": "built",
                "tool_count": len(selected_tools),
                "skill_count": len(selected_skills),
                "source_count": len(sources),
            }
            # B3: a SQL tool that references a table the session never
            # materialized builds clean but errors on every call ("no such
            # table"). Smoke-check each tool's SQL against the loaded schema and
            # surface the broken ones at build time instead of shipping them.
            warnings = _build_table_warnings(session, selected_tools)
            if warnings:
                result["warnings"] = warnings
            return result
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("connector.build.failed", error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_export_connector(
        path: str = ".elliot/connector.json",
        allow_warnings: bool = False,
    ) -> dict:  # type: ignore[type-arg]
        """Lint the built ConnectorConfig, then write it to disk as JSON.

        A connector is a contract, so export is GATED on the linter — it will not
        ship a connector that fails it. Lint ERRORS always block. Lint WARNINGS
        also block by default (the workflow expects zero warnings before export);
        pass ``allow_warnings=true`` to ship with warnings present. Errors can
        never be overridden. Run ``elliot_lint_connector`` to see the issues.
        """
        try:
            import dataclasses

            from elliot_core.linter import lint_connector
            from elliot_core.paths import PathEscape, ensure_under

            if session.connector is None:
                return {"error": "No connector built yet — call elliot_build_connector first"}

            # Lint gate — never ship a broken contract (principle 1). Errors are
            # absolute; warnings block unless the caller explicitly opts in.
            issues = lint_connector(session.connector)
            errors = [i for i in issues if i.severity == "ERROR"]
            warnings = [i for i in issues if i.severity == "WARN"]
            if errors or (warnings and not allow_warnings):
                return to_mcp_error_content(
                    ElliotError(
                        "EXPORT_LINT_FAILED",
                        (
                            f"Connector did not pass the linter: {len(errors)} error(s), "
                            f"{len(warnings)} warning(s). Fix them before exporting"
                            + (
                                " (or pass allow_warnings=true to ship with warnings; "
                                "errors always block)."
                                if warnings and not errors
                                else "."
                            )
                        ),
                        detail={
                            "errors": [dataclasses.asdict(i) for i in errors],
                            "warnings": [dataclasses.asdict(i) for i in warnings],
                        },
                    )
                )
            # Containment: the resolved destination must live under the
            # session cwd (workspace._dir.parent), ELLIOT_CONNECTORS_DIR, or
            # the parent of ELLIOT_CONNECTOR. Opt-out via
            # ELLIOT_ALLOW_ABSOLUTE_CONNECTOR_PATH=1 for non-standard layouts.
            project_root = Path(session.workspace._dir).resolve().parent
            allowed_roots = [project_root]
            connectors_dir_env = os.environ.get("ELLIOT_CONNECTORS_DIR")
            if connectors_dir_env:
                allowed_roots.append(Path(connectors_dir_env).resolve())
            env_connector = os.environ.get("ELLIOT_CONNECTOR")
            if env_connector:
                allowed_roots.append(Path(env_connector).resolve().parent)
            # Resolve relative paths against the project root so the default
            # ".elliot/connector.json" continues to land where it always did.
            candidate = path if os.path.isabs(path) else str(project_root / path)
            dest = Path(candidate)
            if os.environ.get("ELLIOT_ALLOW_ABSOLUTE_CONNECTOR_PATH", "").strip().lower() not in {
                "1",
                "true",
                "yes",
                "on",
            }:
                contained = False
                for root in allowed_roots:
                    try:
                        ensure_under(root, dest)
                        contained = True
                        break
                    except PathEscape:
                        continue
                if not contained:
                    return to_mcp_error_content(
                        ElliotError(
                            "EXPORT_PATH_NOT_ALLOWED",
                            "Export path is outside the allowed roots (project root, "
                            "ELLIOT_CONNECTORS_DIR, ELLIOT_CONNECTOR parent). "
                            "Set ELLIOT_ALLOW_ABSOLUTE_CONNECTOR_PATH=1 to opt out.",
                            detail={"path": str(dest)},
                        )
                    )
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write — never leave a half-written connector file on disk
            # if the write is interrupted (audit Low 33).
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_text(serialize_connector(session.connector))
            os.replace(tmp, dest)
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

            result: dict[str, object] = {
                "status": "exported",
                "path": str(dest),
                "lint": {"errors": 0, "warnings": len(warnings)},
            }
            if warnings:
                # Shipped with warnings (allow_warnings=true) — surface them so
                # the agent still sees what to improve.
                result["lint_warnings"] = [dataclasses.asdict(i) for i in warnings]
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

            # Audit finding C5: previously connector_path was an agent-supplied
            # string written straight into the child uvicorn's env. An attacker
            # who could call save_draft (C4) could then point the runtime at
            # any file on disk. Enforce that the resolved connector path lives
            # under the session cwd (typically the project root), the
            # ELLIOT_CONNECTORS_DIR, or the directory of ELLIOT_CONNECTOR.
            # Operators with non-standard layouts can opt out via
            # ELLIOT_ALLOW_ABSOLUTE_CONNECTOR_PATH=1.
            from elliot_core.paths import PathEscape, ensure_under

            if os.environ.get("ELLIOT_ALLOW_ABSOLUTE_CONNECTOR_PATH", "").strip().lower() not in {
                "1",
                "true",
                "yes",
                "on",
            }:
                # Workspace _dir is e.g. <cwd>/.elliot, so the project root
                # (workspace._dir.parent) is the default allowlist root.
                allowed_roots = [Path(workspace_dir).resolve().parent]
                connectors_dir_env = os.environ.get("ELLIOT_CONNECTORS_DIR")
                if connectors_dir_env:
                    allowed_roots.append(Path(connectors_dir_env).resolve())
                env_connector = os.environ.get("ELLIOT_CONNECTOR")
                if env_connector:
                    allowed_roots.append(Path(env_connector).resolve().parent)

                contained = False
                for root in allowed_roots:
                    try:
                        ensure_under(root, chosen_connector)
                        contained = True
                        break
                    except PathEscape:
                        continue
                if not contained:
                    return to_mcp_error_content(
                        ElliotError(
                            "RUNTIME_BAD_CONNECTOR_PATH",
                            (
                                "connector_path is outside the allowed roots "
                                "(project root, ELLIOT_CONNECTORS_DIR, ELLIOT_CONNECTOR parent). "
                                "Set ELLIOT_ALLOW_ABSOLUTE_CONNECTOR_PATH=1 to opt out."
                            ),
                            detail={"connector_path": chosen_connector},
                        )
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
                    # Own process group/session so _kill_process_tree can take
                    # down the uvicorn grandchild too (POSIX). Ignored on Windows,
                    # where taskkill /T walks the tree by PID instead (F-024).
                    start_new_session=(sys.platform != "win32"),
                )
            finally:
                # The subprocess inherits the fd; we can safely close our handle.
                log_fh.close()

            session.runtime_process = proc
            session.runtime_log_path = log_path

            deadline = time.monotonic() + _RUNTIME_HEALTH_TIMEOUT_S
            ok, reason = _wait_for_runtime(proc, f"http://localhost:{port}/health", deadline)
            if not ok:
                # Kill the whole tree (uv + uvicorn grandchild), not just uv,
                # so a half-started runtime doesn't keep the port (F-024).
                _kill_process_tree(proc)
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
            # Kill the whole process tree. `uv run uvicorn` makes uvicorn a
            # grandchild; terminating only the `uv` parent orphaned uvicorn,
            # which kept port 3001 and went on serving the OLD connector across
            # a stop+start (F-024). A fresh start now binds a free port and the
            # newly-exported connector is actually served.
            _kill_process_tree(session.runtime_process)
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
