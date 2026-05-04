from __future__ import annotations

from pydantic import BaseModel, model_validator

from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import SkillDefinition, ToolDefinition


class ConnectorConfig(BaseModel):
    name: str
    slug: str
    version: str
    description: str = ""
    sources: list[SourceConfig] = []
    tools: list[ToolDefinition] = []
    skills: list[SkillDefinition] = []

    @model_validator(mode="after")
    def _validate_source_refs(self) -> "ConnectorConfig":
        source_ids = {s.id for s in self.sources}
        for tool in self.tools:
            for sid in tool.source_ids:
                if sid not in source_ids:
                    raise ValueError(
                        f"Tool '{tool.id}' references unknown source '{sid}'. "
                        f"Available: {sorted(source_ids)}"
                    )
            if tool.category == "READ" and not tool.source_ids:
                raise ValueError(
                    f"READ tool '{tool.id}' must declare at least one source_id"
                )
        return self
