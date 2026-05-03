# 019 — Skill Runner + Binding Resolver

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 018

## Files to Create

### `packages/core/src/elliot_core/tools/skill_runner.py`
```python
import re
import jmespath
from typing import Any
from elliot_core.types.tool import SkillDefinition, ToolResult
from elliot_core.tools.registry import ToolRegistry
from elliot_core.tools.executor import execute_tool
from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.errors import ElliotError

def execute_skill(
    skill: SkillDefinition,
    inputs: dict[str, Any],
    registry: ToolRegistry,
    engine: SQLiteEngine,
) -> ToolResult:
    step_results: dict[str, ToolResult] = {}
    last_result: ToolResult | None = None
    for step in skill.steps:
        tool = registry.get_by_name(step.tool_name)
        if not tool:
            raise ElliotError("TOOL_NOT_FOUND", f"Skill step references unknown tool: {step.tool_name}")
        resolved_params = resolve_bindings(step.params, inputs, step_results)
        result = execute_tool(tool, resolved_params, engine)
        step_results[step.alias] = result
        last_result = result
    if last_result is None:
        raise ElliotError("SKILL_EMPTY", "Skill has no steps")
    return last_result

def resolve_bindings(
    template: dict[str, Any],
    inputs: dict[str, Any],
    step_results: dict[str, ToolResult],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, val in template.items():
        result[key] = _resolve_value(val, inputs, step_results)
    return result

def _resolve_value(val: Any, inputs: dict, step_results: dict[str, ToolResult]) -> Any:
    if not isinstance(val, str):
        return val
    # {{skill.input.X}}
    m = re.fullmatch(r"\{\{skill\.input\.(.+?)\}\}", val)
    if m:
        return inputs.get(m.group(1))
    # {{steps.ALIAS.FIELD}} - use jmespath on first row of that step
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
- [ ] `{{skill.input.X}}` resolves from `inputs`
- [ ] `{{steps.ALIAS.FIELD}}` resolves from previous step's first row
- [ ] Step failure raises `ElliotError` with step alias in message
