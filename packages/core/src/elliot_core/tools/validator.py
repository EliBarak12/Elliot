from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from elliot_core.errors import ElliotError
from elliot_core.types.tool import SkillDefinition, ToolDefinition

_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_GENERIC_IDS = frozenset({"query", "get_data", "fetch", "run", "execute", "call"})


def validate_tool_definition(data: dict[str, Any]) -> ToolDefinition:
    """Parse and validate a tool definition dict. Raises ElliotError on failure."""
    try:
        tool = ToolDefinition.model_validate(data)
    except ValidationError as exc:
        raise ElliotError("INVALID_TOOL", str(exc)) from exc

    _check_id(tool)
    _check_description(tool)
    _check_category_requirements(tool)
    _check_filter_param_refs(tool)
    return tool


def _check_id(tool: ToolDefinition) -> None:
    if not _SNAKE_RE.fullmatch(tool.id):
        raise ElliotError("INVALID_TOOL", f"Tool id must be snake_case, got: '{tool.id}'")
    if tool.id in _GENERIC_IDS:
        raise ElliotError("INVALID_TOOL", f"Tool id '{tool.id}' is too generic — be specific")


def _check_description(tool: ToolDefinition) -> None:
    if len(tool.description.strip()) < 10:
        raise ElliotError(
            "INVALID_TOOL",
            f"Tool '{tool.id}' description too short (min 10 chars)",
        )


def _check_category_requirements(tool: ToolDefinition) -> None:
    if tool.category in ("READ",) and not tool.source_ids:
        raise ElliotError(
            "INVALID_TOOL",
            f"READ tool '{tool.id}' must have at least one source_id",
        )
    if tool.category in ("WRITE", "ACTION") and tool.api_mapping is None:
        raise ElliotError(
            "INVALID_TOOL",
            f"WRITE/ACTION tool '{tool.id}' must have api_mapping",
        )


def _check_filter_param_refs(tool: ToolDefinition) -> None:
    defined = {p.name for p in tool.parameters}
    for group in tool.filter_groups:
        for cond in group.conditions:
            if cond.parameter_name and cond.parameter_name not in defined:
                raise ElliotError(
                    "INVALID_TOOL",
                    f"Tool '{tool.id}': filter condition references undefined "
                    f"parameter '{cond.parameter_name}'",
                )


def validate_skill_definition(data: dict[str, Any]) -> SkillDefinition:
    try:
        return SkillDefinition.model_validate(data)
    except ValidationError as exc:
        raise ElliotError("INVALID_SKILL", str(exc)) from exc
