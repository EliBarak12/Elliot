from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from elliot_core.errors import ElliotError
from elliot_core.sql import extract_sql_params
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
    _check_sql_bind_params(tool)
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
    if (
        tool.category in ("WRITE", "ACTION")
        and tool.api_mapping is None
        and tool.data_mapping is None
    ):
        raise ElliotError(
            "INVALID_TOOL",
            f"WRITE/ACTION tool '{tool.id}' must have api_mapping (REST mutation) "
            "or data_mapping (managed-source mutation)",
        )
    if tool.data_mapping is not None:
        _check_data_mapping(tool)


def _check_data_mapping(tool: ToolDefinition) -> None:
    mapping = tool.data_mapping
    assert mapping is not None
    if tool.api_mapping is not None:
        raise ElliotError(
            "INVALID_TOOL",
            f"Tool '{tool.id}' declares BOTH api_mapping and data_mapping — a tool "
            "mutates either a REST API or a managed source, not both",
        )
    declared = {p.name for p in tool.parameters}
    undeclared = sorted(
        {param for param in mapping.column_params.values() if param not in declared}
    )
    if mapping.key_param and mapping.key_param not in declared:
        undeclared.append(mapping.key_param)
    if undeclared:
        raise ElliotError(
            "INVALID_TOOL",
            f"Tool '{tool.id}': data_mapping references undeclared parameter(s): "
            f"{', '.join(sorted(set(undeclared)))}",
        )
    if mapping.operation == "insert" and not mapping.column_params:
        raise ElliotError(
            "INVALID_TOOL",
            f"Tool '{tool.id}': a managed insert must map at least one column_param",
        )
    if mapping.operation in ("update", "delete") and not mapping.key_param:
        raise ElliotError(
            "INVALID_TOOL",
            f"Tool '{tool.id}': a managed {mapping.operation} must declare key_param "
            "(the parameter carrying the target row's _id)",
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


def _check_sql_bind_params(tool: ToolDefinition) -> None:
    """Every ``:name`` the SQL binds must be a declared parameter.

    Without this, a tool whose SQL references ``:foo`` with no matching entry in
    ``parameters`` validates fine and only fails at call time with SQLite's
    cryptic "You did not supply a value for binding parameter :foo" — a broken
    tool that passes validation and breaks in production. ``elliot_create_tool``
    already guards this in the MCP layer; checking it here means
    ``elliot_validate_tool`` (and every other caller of the core validator)
    catches it too.
    """
    if not tool.sql:
        return
    declared = {p.name for p in tool.parameters}
    undeclared = [name for name in extract_sql_params(tool.sql) if name not in declared]
    if undeclared:
        raise ElliotError(
            "INVALID_TOOL",
            f"Tool '{tool.id}': SQL references undeclared bind parameter(s): "
            f"{', '.join(undeclared)}. Declare each in `parameters` "
            "(or remove the ':' reference).",
            detail={"undeclared": undeclared, "declared": sorted(declared)},
        )


def validate_skill_definition(data: dict[str, Any]) -> SkillDefinition:
    try:
        return SkillDefinition.model_validate(data)
    except ValidationError as exc:
        raise ElliotError("INVALID_SKILL", str(exc)) from exc
