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
        log.info(
            "session.saved",
            sources=len(self.sources),
            tools=len(self.registry.get_all()),
        )
