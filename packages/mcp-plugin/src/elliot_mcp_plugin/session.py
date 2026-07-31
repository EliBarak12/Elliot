from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import structlog

from elliot_core import ConnectorBuilder, SQLiteEngine, ToolRegistry, WorkspaceStore
from elliot_core.audit.models import AuditTranscript, ProductIntent
from elliot_core.sql import safe_ident
from elliot_core.types.connector import ConnectorBranding, ConnectorConfig, ProductContext
from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import SkillDefinition, ToolDefinition
from elliot_mcp_plugin.oauth_login import BuildOAuthLogin

log = structlog.get_logger(__name__)


class ElliotSession:
    def __init__(self, cwd: str = ".") -> None:
        self.engine = SQLiteEngine()
        self.registry = ToolRegistry()
        self.builder = ConnectorBuilder()
        self.workspace = WorkspaceStore(cwd)
        self.sources: dict[str, SourceConfig] = {}
        # In-flight / completed builder OAuth logins for discover, keyed by
        # source name. In-memory only and never persisted: the builder's token
        # is used to fetch discovery samples and discarded, never written into
        # session.json or the connector file.
        self.oauth_logins: dict[str, BuildOAuthLogin] = {}
        self.product_context: ProductContext | None = None
        # Connector-level brand identity (accent colors + logo) applied to
        # every MCP Apps view. Lives on the session so it survives rebuilds
        # and flows into each ConnectorConfig produced by build_connector.
        self.branding: ConnectorBranding | None = None
        self.runtime_process: subprocess.Popen[Any] | None = None
        self.runtime_log_path: Path | None = None
        self.tool_sql: dict[str, str] = {}
        self.connector: ConnectorConfig | None = None
        # Stable id of the connector the last ``build_connector`` produced. Used
        # to scope audit transcripts to the build they were recorded against so
        # a re-judge reflects the CURRENT connector, not stale prior-build runs.
        self.build_id: str = ""
        # Onboarding interview answers + Petri-style audit transcripts.
        self.product_intent: ProductIntent | None = None
        self.audit_transcripts: list[AuditTranscript] = []
        # mtime of session.json the last time we synced it into memory.
        # Used by `refresh_from_disk` to skip the reload when nothing changed.
        self._last_loaded_mtime: float | None = None

    def _session_path(self) -> Path:
        return self.workspace._dir / "session.json"

    def load(self) -> None:
        data = self.workspace.load_session()
        if not data:
            return
        if data.get("product_context"):
            self.product_context = ProductContext(**data["product_context"])
        if data.get("branding"):
            self.branding = ConnectorBranding.model_validate(data["branding"])
        for s in data.get("sources", []):
            src = SourceConfig.model_validate(s)
            self.sources[src.id] = src
        for t in data.get("tools", []):
            self.registry.add(ToolDefinition.model_validate(t))
        for sk in data.get("skills", []):
            self.registry.add_skill(SkillDefinition.model_validate(sk))
        self.tool_sql = data.get("tool_sql", {})
        # Restore the built connector so cloud / judge tools don't report
        # NO_CONNECTOR after a reload even though sources+tools persisted.
        if data.get("connector"):
            self.connector = ConnectorConfig.model_validate(data["connector"])
        self.build_id = data.get("build_id", "")
        if data.get("product_intent"):
            self.product_intent = ProductIntent.model_validate(data["product_intent"])
        self.audit_transcripts = [
            AuditTranscript.model_validate(t) for t in data.get("audit_transcripts", [])
        ]
        self._track_mtime()
        log.info("session.loaded", sources=len(self.sources), tools=len(self.registry.get_all()))

    def save(self) -> None:
        self.workspace.save_session(
            {
                "product_context": (
                    self.product_context.model_dump() if self.product_context else None
                ),
                "branding": (self.branding.model_dump() if self.branding else None),
                "sources": [s.model_dump() for s in self.sources.values()],
                "tools": [t.model_dump() for t in self.registry.get_all()],
                "skills": [s.model_dump() for s in self.registry.get_all_skills()],
                "tool_sql": self.tool_sql,
                "connector": (self.connector.model_dump(mode="json") if self.connector else None),
                "build_id": self.build_id,
                "product_intent": (
                    self.product_intent.model_dump() if self.product_intent else None
                ),
                "audit_transcripts": [t.model_dump() for t in self.audit_transcripts],
            }
        )
        # Track our own write so refresh_from_disk treats it as up-to-date and
        # doesn't re-read the file we just produced.
        self._track_mtime()
        log.info(
            "session.saved",
            sources=len(self.sources),
            tools=len(self.registry.get_all()),
        )

    def _track_mtime(self) -> None:
        path = self._session_path()
        try:
            self._last_loaded_mtime = path.stat().st_mtime
        except FileNotFoundError:
            self._last_loaded_mtime = None

    def remove_source(self, source_id: str) -> dict[str, Any]:
        """Remove a source, drop its SQLite table, and cascade-delete dependent tools.

        Source removal is a destructive user-driven action (Studio button,
        Cloud dashboard button). Tools whose ``source_ids`` reference this
        source are deleted in the same step so the registry doesn't keep
        orphaned definitions that would fail at call time.

        Returns ``{"status": "removed", ...}`` on success, or
        ``{"error": "..."}`` if the source isn't found.
        """
        src = self.sources.pop(source_id, None)
        if src is None:
            return {"error": f"Source not found: {source_id}"}
        removed_tool_ids = [
            t.id for t in self.registry.get_all() if source_id in (t.source_ids or [])
        ]
        for tid in removed_tool_ids:
            self.registry.delete(tid)
            self.tool_sql.pop(tid, None)
        if src.table_name:
            # Validate + quote the identifier rather than hand-rolling the
            # double-quote — a table name carrying a quote would otherwise be a
            # DROP-TABLE injection.
            self.engine._conn.execute(f"DROP TABLE IF EXISTS {safe_ident(src.table_name)}")
            self.engine._conn.commit()
        self.save()
        log.info(
            "source.removed",
            source_id=source_id,
            table=src.table_name,
            removed_tools=removed_tool_ids,
        )
        return {
            "status": "removed",
            "source_id": source_id,
            "table": src.table_name,
            "removed_tool_ids": removed_tool_ids,
        }

    def discard_connector(self) -> dict[str, Any]:
        """Discard the in-flight built connector and remove its exported file.

        Clears ``session.connector`` and deletes ``.elliot/connector.json`` if
        present. Sources, tools, and skills in ``session.json`` are left
        alone — the user is just resetting the assembly step so the agent can
        rebuild via ``elliot_build_connector``. Used by the Studio button
        and the Cloud dashboard's "Discard connector" action.
        """
        had_connector = self.connector is not None
        self.connector = None
        self.build_id = ""
        path = self.workspace._dir / "connector.json"
        removed_file = False
        try:
            path.unlink()
            removed_file = True
        except FileNotFoundError:
            pass
        log.info("connector.discarded", had_connector=had_connector, removed_file=removed_file)
        return {
            "status": "discarded",
            "had_connector": had_connector,
            "removed_file": removed_file,
        }

    def refresh_from_disk(self) -> bool:
        """Re-sync in-memory state from session.json if the file has changed.

        Returns True if a reload happened. Cheap when nothing changed
        (one stat() call), so safe to call on every list endpoint to
        keep the Studio in sync with whatever the agent — possibly
        running in a separate plugin process sharing the same workspace
        — has just written. ``runtime_process`` and the in-memory SQLite
        engine are left alone; only the metadata that lives in
        session.json is replaced.
        """
        path = self._session_path()
        try:
            current_mtime = path.stat().st_mtime
        except FileNotFoundError:
            return False
        if self._last_loaded_mtime is not None and current_mtime <= self._last_loaded_mtime:
            return False
        # The file is newer than our in-memory snapshot. Drop the metadata we
        # serialise into session.json and re-read it. Anything not persisted
        # (engine, runtime_process, builder) stays untouched.
        self.registry.clear()
        self.sources.clear()
        self.tool_sql = {}
        self.product_context = None
        self.branding = None
        self.connector = None
        self.build_id = ""
        self.product_intent = None
        self.audit_transcripts = []
        self.load()
        return True
