from __future__ import annotations

from typing import Any

from elliot_core.types.tool import ToolDefinition

_TYPE_MAP: dict[str, str] = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "date": "string",
}


def _param_schema(p: Any) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": _TYPE_MAP.get(p.type, "string"),
        "description": p.description,
    }
    if p.type == "date":
        schema["format"] = "date"
    if p.enum is not None:
        schema["enum"] = p.enum
    if p.default is not None:
        schema["default"] = p.default
    return schema


def _tool_annotations(tool: ToolDefinition) -> dict[str, Any]:
    read_only = tool.category == "READ"
    return {
        "title": tool.name,
        "readOnlyHint": read_only,
        "destructiveHint": tool.category in ("WRITE", "ACTION"),
        "idempotentHint": read_only,
        "openWorldHint": True,
    }


def to_mcp_tool_schema(tool: ToolDefinition) -> dict[str, Any]:
    """Convert ToolDefinition to MCP tools/list JSON Schema entry."""
    props = {p.name: _param_schema(p) for p in tool.parameters}
    required = [p.name for p in tool.parameters if p.required]
    schema: dict[str, Any] = {
        "name": tool.id,
        "description": tool.description,
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": required,
        },
        "annotations": _tool_annotations(tool),
    }
    if tool.output_schema is not None:
        schema["outputSchema"] = tool.output_schema
    return schema


def to_openai_function(tool: ToolDefinition) -> dict[str, Any]:
    """Convert ToolDefinition to OpenAI function-calling tool descriptor."""
    props = {p.name: _param_schema(p) for p in tool.parameters}
    required = [p.name for p in tool.parameters if p.required]
    return {
        "type": "function",
        "function": {
            "name": tool.id,
            "description": tool.description,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
                "additionalProperties": False,
            },
        },
    }
