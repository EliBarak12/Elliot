from __future__ import annotations

from typing import Any

from elliot_core.errors import ElliotError
from elliot_core.types.connector import ConnectorBranding, ConnectorConfig
from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import SkillDefinition, ToolDefinition


class ConnectorBuilder:
    def __init__(self) -> None:
        self._meta: dict[str, Any] = {}

    def set_meta(
        self,
        name: str,
        version: str,
        slug: str,
        description: str = "",
        instructions: str = "",
    ) -> ConnectorBuilder:
        self._meta = {
            "name": name,
            "version": version,
            "slug": slug,
            "description": description,
            "instructions": instructions,
        }
        return self

    def build(
        self,
        sources: list[SourceConfig],
        tools: list[ToolDefinition],
        skills: list[SkillDefinition] | None = None,
        branding: ConnectorBranding | None = None,
    ) -> ConnectorConfig:
        if not self._meta:
            raise ElliotError("INVALID_CONNECTOR", "Call set_meta() before build()")
        return ConnectorConfig(
            **self._meta,
            sources=sources,
            tools=tools,
            skills=skills or [],
            branding=branding,
        )
