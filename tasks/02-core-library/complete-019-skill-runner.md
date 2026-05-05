# 019 — Skill Runner + Binding Resolver

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 018

## Files to Create

### `packages/core/src/elliot_core/tools/skill_runner.py`
```python
from __future__ import annotations

import re
from typing import Any

import jmespath

from elliot_core.errors import ElliotError
from elliot_core.tools.executor import ToolExecutor
from elliot_core.tools.registry import ToolRegistry
from elliot_core.types.tool import SkillDefinition, ToolResult


async def execute_skill(
    skill: SkillDefinition,
    inputs: dict[str, Any],
    registry: ToolRegistry,
    executor: ToolExecutor,
) -> ToolResult:
    """Run each skill step in sequence, piping outputs into subsequent step inputs."""
    step_results: dict[str, ToolResult] = {}
    last_result: ToolResult | None = None

    for step in skill.steps:
        tool = registry.get_by_id(step.tool_id)
        if tool is None:
            raise ElliotError(
                "TOOL_NOT_FOUND",
                f"Skill '{skill.id}' step '{step.alias}' references unknown tool '{step.tool_id}'",
            )

        resolved = resolve_bindings(step.params, inputs, step_results)
        try:
            result = await executor.execute(tool, resolved)
        except ElliotError:
            raise
        except Exception as exc:
            raise ElliotError(
                "SKILL_STEP_FAILED", f"Step '{step.alias}' failed: {exc}"
            ) from exc

        step_results[step.alias] = result
        last_result = result

    if last_result is None:
        raise ElliotError("SKILL_EMPTY", f"Skill '{skill.id}' has no steps")
    return last_result


def resolve_bindings(
    template: dict[str, Any],
    inputs: dict[str, Any],
    step_results: dict[str, ToolResult],
) -> dict[str, Any]:
    return {k: _resolve_value(v, inputs, step_results) for k, v in template.items()}


def _resolve_value(val: Any, inputs: dict, step_results: dict[str, ToolResult]) -> Any:
    if not isinstance(val, str):
        return val

    # {{skill.input.X}}
    m = re.fullmatch(r"\{\{skill\.input\.(.+?)\}\}", val)
    if m:
        return inputs.get(m.group(1))

    # {{steps.ALIAS.FIELD}} — jmespath on first row of that step
    m = re.fullmatch(r"\{\{steps\.([^.]+)\.(.+?)\}\}", val)
    if m:
        alias, path = m.group(1), m.group(2)
        step = step_results.get(alias)
        if step and step.rows:
            return jmespath.search(path, step.rows[0])
        return None

    return val
```

## Done When
- [ ] `{{skill.input.X}}` resolves from `inputs` dict
- [ ] `{{steps.ALIAS.FIELD}}` resolves from previous step's first row via jmespath
- [ ] Step referencing unknown tool raises `ElliotError("TOOL_NOT_FOUND")`
- [ ] Empty skill raises `ElliotError("SKILL_EMPTY")`
- [ ] All steps run sequentially (not parallel)
