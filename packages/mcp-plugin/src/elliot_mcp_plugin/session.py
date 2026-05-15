from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import structlog

from elliot_core import ConnectorBuilder, SQLiteEngine, ToolRegistry, WorkspaceStore
from elliot_core.types.connector import ConnectorConfig, ProductContext
from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import SkillDefinition, ToolDefinition

log = structlog.get_logger(__name__)


class ElliotSession:
    def __init__(self, cwd: str = ".") -> None:
        self.engine = SQLiteEngine()
        self.registry = ToolRegistry()
        self.builder = ConnectorBuilder()
        self.workspace = WorkspaceStore(cwd)
        self.sources: dict[str, SourceConfig] = {}
        self.product_context: ProductContext | None = None
        self.runtime_process: subprocess.Popen[Any] | None = None
        self.runtime_log_path: Path | None = None
        self.tool_sql: dict[str, str] = {}
        self.connector: ConnectorConfig | None = None
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
        for s in data.get("sources", []):
            src = SourceConfig.model_validate(s)
            self.sources[src.id] = src
        for t in data.get("tools", []):
            self.registry.add(ToolDefinition.model_validate(t))
        for sk in data.get("skills", []):
            self.registry.add_skill(SkillDefinition.model_validate(sk))
        self.tool_sql = data.get("tool_sql", {})
        self._track_mtime()
        log.info("session.loaded", sources=len(self.sources), tools=len(self.registry.get_all()))

    def save(self) -> None:
        self.workspace.save_session(
            {
                "product_context": (
                    self.product_context.model_dump() if self.product_context else None
                ),
                "sources": [s.model_dump() for s in self.sources.values()],
                "tools": [t.model_dump() for t in self.registry.get_all()],
                "skills": [s.model_dump() for s in self.registry.get_all_skills()],
                "tool_sql": self.tool_sql,
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
        self.connector = None
        self.load()
        return True
