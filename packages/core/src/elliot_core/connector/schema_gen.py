from __future__ import annotations

from typing import Any

from elliot_core.danger_zone import is_destructive
from elliot_core.types.tool import ToolDefinition

_TYPE_MAP: dict[str, str] = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "date": "string",
    "object": "object",
}


def _param_schema(p: Any) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": _TYPE_MAP.get(p.type, "string"),
        "description": p.description,
    }
    if p.type == "date":
        schema["format"] = "date"
    if p.type == "object":
        # Dynamic-key map: arbitrary string keys, any JSON value.
        schema["additionalProperties"] = True
    if p.enum is not None:
        schema["enum"] = p.enum
    if p.default is not None:
        schema["default"] = p.default
    return schema


def _tool_annotations(tool: ToolDefinition) -> dict[str, Any]:
    read_only = tool.category == "READ"
    # destructiveHint follows Elliot's danger-zone model, not a blanket "every
    # write is destructive": an additive create/update/send is safe to auto-run,
    # so a spec-respecting client must not gate it. Only a truly destructive verb
    # (or an explicit ``destructive: true``) flips the hint — matching the
    # runtime's confirmation gate exactly, since both call ``is_destructive``.
    return {
        "title": tool.name,
        "readOnlyHint": read_only,
        "destructiveHint": is_destructive(tool.category, tool.id, tool.destructive),
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


def _openai_strict_param_schema(p: Any) -> dict[str, Any]:
    """Build a parameter schema valid under OpenAI strict function calling.

    Strict mode requires every property to appear in ``required`` and forbids
    keywords like ``default``. An optional parameter is therefore modelled as
    nullable (``type: [<type>, "null"]``) rather than omitted from required.
    """
    base_type = _TYPE_MAP.get(p.type, "string")
    schema: dict[str, Any] = {"description": p.description}
    schema["type"] = base_type if p.required else [base_type, "null"]
    if p.enum is not None:
        # A nullable enum must allow null as a member.
        schema["enum"] = list(p.enum) if p.required else [*p.enum, None]
    return schema


def to_openai_function(tool: ToolDefinition) -> dict[str, Any]:
    """Convert ToolDefinition to an OpenAI function-calling tool descriptor.

    Emitted in OpenAI strict mode: every parameter is listed in ``required``
    and optional parameters are nullable, which is what strict + structured
    outputs demand. The previous schema put only required params in
    ``required``, which OpenAI rejects when ``strict`` is true.
    """
    props = {p.name: _openai_strict_param_schema(p) for p in tool.parameters}
    required = [p.name for p in tool.parameters]
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
