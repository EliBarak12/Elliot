from __future__ import annotations

import re
from typing import Any

from elliot_core.errors import ElliotError
from elliot_core.tools.executor import ToolExecutor
from elliot_core.tools.registry import ToolRegistry
from elliot_core.types.tool import SkillDefinition, ToolResult

_TEMPLATE_RE = re.compile(r"\{\{([^}]+)\}\}")


async def execute_skill(
    skill: SkillDefinition,
    inputs: dict[str, Any],
    registry: ToolRegistry,
    executor: ToolExecutor,
) -> ToolResult:
    step_results: dict[str, ToolResult] = {}

    for step in skill.steps:
        tool = registry.get(step.tool_id)
        if not tool:
            raise ElliotError(
                "TOOL_NOT_FOUND", f"Skill step references unknown tool: '{step.tool_id}'"
            )
        resolved = _resolve_bindings(step.params, inputs, step_results)
        result = await executor.execute(step.tool_id, resolved)
        step_results[step.alias] = result

    if not step_results:
        return ToolResult(rows=[], meta={})

    # The skill's primary result is still the final step's rows (a 2-step
    # "look up X, then summarise" skill answers with the summary). But the
    # intermediate steps used to be computed and silently dropped, so a
    # "give me X AND Y" skill returned only Y (audit H7). Expose every step's
    # output under meta.steps so the caller can recover all of them, and mark
    # which alias is the primary one.
    last_alias, last = list(step_results.items())[-1]
    return ToolResult(
        rows=last.rows,
        meta={
            **last.meta,
            "primary_step": last_alias,
            "step_count": len(step_results),
            "steps": {
                alias: {"rows": r.rows, "row_count": len(r.rows), "meta": r.meta}
                for alias, r in step_results.items()
            },
        },
    )


def _resolve_bindings(
    params: dict[str, Any],
    inputs: dict[str, Any],
    step_results: dict[str, ToolResult],
) -> dict[str, Any]:
    return {key: _resolve_value(val, inputs, step_results) for key, val in params.items()}


def _resolve_value(
    value: Any,
    inputs: dict[str, Any],
    step_results: dict[str, ToolResult],
) -> Any:
    if not isinstance(value, str):
        return value

    full_match = _TEMPLATE_RE.fullmatch(value.strip())
    if full_match:
        return _lookup(full_match.group(1).strip(), inputs, step_results)

    def _replace(m: re.Match[str]) -> str:
        result = _lookup(m.group(1).strip(), inputs, step_results)
        return str(result) if result is not None else m.group(0)

    return _TEMPLATE_RE.sub(_replace, value)


def _lookup(
    path: str,
    inputs: dict[str, Any],
    step_results: dict[str, ToolResult],
) -> Any:
    parts = path.split(".")
    if len(parts) >= 3 and parts[0] == "skill" and parts[1] == "input":
        return inputs.get(parts[2])
    if len(parts) >= 3 and parts[0] == "steps":
        alias, field = parts[1], parts[2]
        result = step_results.get(alias)
        if result and result.rows:
            return result.rows[0].get(field)
    return None
