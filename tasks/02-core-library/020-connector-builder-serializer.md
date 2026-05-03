# 020 — Connector Builder + Serializer

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 016

## Files to Create

### `packages/core/src/elliot_core/connector/builder.py`
```python
from elliot_core.types.connector import ConnectorConfig, SourceConfig
from elliot_core.types.tool import ToolDefinition, SkillDefinition
from elliot_core.errors import ElliotError

class ConnectorBuilder:
    def __init__(self) -> None:
        self._meta: dict = {}

    def set_meta(self, name: str, version: str, slug: str, description: str = "") -> None:
        self._meta = {"name": name, "version": version, "slug": slug, "description": description}

    def build(
        self,
        sources: list[SourceConfig],
        tools: list[ToolDefinition],
        skills: list[SkillDefinition],
    ) -> ConnectorConfig:
        if not self._meta:
            raise ElliotError("INVALID_CONNECTOR", "Call set_meta() before build()")
        return ConnectorConfig(**self._meta, sources=sources, tools=tools, skills=skills)
```

### `packages/core/src/elliot_core/connector/serializer.py`
```python
import json
from elliot_core.types.connector import ConnectorConfig
from elliot_core.errors import ElliotError

def serialize_connector(config: ConnectorConfig) -> str:
    return config.model_dump_json(indent=2)

def deserialize_connector(json_str: str) -> ConnectorConfig:
    try:
        return ConnectorConfig.model_validate_json(json_str)
    except Exception as e:
        raise ElliotError("INVALID_CONNECTOR", str(e))
```

### `packages/core/src/elliot_core/connector/schema_gen.py`
```python
from elliot_core.types.tool import ToolDefinition

TYPE_MAP = {"string": "string", "integer": "integer", "number": "number", "boolean": "boolean", "date": "string"}

def to_mcp_tool_schema(tool: ToolDefinition) -> dict:
    """Convert ToolDefinition to MCP tools/list JSON Schema."""
    props = {p.name: {"type": TYPE_MAP[p.type], "description": p.description} for p in tool.parameters}
    required = [p.name for p in tool.parameters if p.required]
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": {"type": "object", "properties": props, "required": required},
    }

def to_openai_function(tool: ToolDefinition) -> dict:
    """Convert ToolDefinition to OpenAI function-calling schema."""
    ...
```

## Done When
- [ ] `serialize_connector` then `deserialize_connector` produces identical `ConnectorConfig`
- [ ] `deserialize_connector` with invalid JSON raises `ElliotError("INVALID_CONNECTOR")`
- [ ] MCP schema has correct `required` array
