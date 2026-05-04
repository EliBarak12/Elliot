from __future__ import annotations

from elliot_core.types.tool import ToolDefinition

_TYPE_MAP: dict[str, str] = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "date": "string",
}


def to_mcp_tool_schema(tool: ToolDefinition) -> dict:
    """Convert ToolDefinition to MCP tools/list JSON Schema entry."""
    props = {
        p.name: {"type": _TYPE_MAP.get(p.type, "string"), "description": p.description}
        for p in tool.parameters
    }
    required = [p.name for p in tool.parameters if p.required]
    return {
        "name": tool.id,
        "description": tool.description,
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": required,
        },
    }


def to_openai_function(tool: ToolDefinition) -> dict:
    """Convert ToolDefinition to OpenAI function-calling tool descriptor."""
    props = {
        p.name: {"type": _TYPE_MAP.get(p.type, "string"), "description": p.description}
        for p in tool.parameters
    }
    required = [p.name for p in tool.parameters if p.required]
    return {
        "type": "function",
        "function": {
            "name": tool.id,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        },
    }
