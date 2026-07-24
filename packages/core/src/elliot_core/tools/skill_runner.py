from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from elliot_core.errors import ElliotError
from elliot_core.tools.executor import ToolExecutor
from elliot_core.tools.registry import ToolRegistry
from elliot_core.types.tool import SkillDefinition, ToolResult

_TEMPLATE_RE = re.compile(r"\{\{([^}]+)\}\}")

# One step's executor: given a tool id and its resolved params, run it and return
# the ToolResult. Design time binds tool ids through a ToolRegistry + the core
# executor; the published runtime binds them to ToolDefinitions + a per-user
# executor — so the orchestration takes this callable instead of a concrete
# executor, and works identically on both surfaces.
RunStep = Callable[[str, dict[str, Any]], Awaitable[ToolResult]]


async def run_skill_steps(
    skill: SkillDefinition,
    inputs: dict[str, Any],
    run_step: RunStep,
) -> ToolResult:
    """Execute a skill's deterministic step chain, resolving ``{{ skill.input.X }}``
    and ``{{ steps.<alias>.<field> }}`` bindings between steps.

    ``run_step(tool_id, params)`` executes one tool and returns its result — the
    caller supplies it, so the same orchestration drives both the design-time
    preview (registry + core executor) and the published runtime (per-user
    executor over ToolDefinitions). This is what lets a deterministic skill run
    as a single call on both surfaces instead of only at build time."""
    step_results: dict[str, ToolResult] = {}

    for step in skill.steps:
        resolved = _resolve_bindings(step.params, inputs, step_results)
        result = await run_step(step.tool_id, resolved)
        step_results[step.alias] = result

    if not step_results:
        return ToolResult(rows=[], meta={})

    # The skill's primary result is still the final step's rows (a 2-step
    # "look up X, then summarise" skill answers with the summary). But the
    # intermediate steps used to be computed and silently dropped, so a
    # "give me X AND Y" skill returned only Y (audit H7). Expose every step's
    # output under meta.steps so the caller can recover all of them, and mark
    # which alias is the primary one.
    # Step results may be a design-time ToolResult (has ``.meta``) or the
    # published runtime's QueryResult (has ``.rows`` but no ``.meta``); read meta
    # defensively so the same orchestration works on both surfaces.
    def _meta_of(r: Any) -> dict[str, Any]:
        m = getattr(r, "meta", None)
        return m if isinstance(m, dict) else {}

    last_alias, last = list(step_results.items())[-1]
    return ToolResult(
        rows=last.rows,
        meta={
            **_meta_of(last),
            "primary_step": last_alias,
            "step_count": len(step_results),
            "steps": {
                alias: {"rows": r.rows, "row_count": len(r.rows), "meta": _meta_of(r)}
                for alias, r in step_results.items()
            },
        },
    )


async def execute_skill(
    skill: SkillDefinition,
    inputs: dict[str, Any],
    registry: ToolRegistry,
    executor: ToolExecutor,
) -> ToolResult:
    """Design-time skill execution: bind each step's tool id through the session
    ``registry`` (existence-checked) and run it on the core ``executor``. Thin
    wrapper over :func:`run_skill_steps` so the preview and runtime share one
    orchestration."""

    async def _run_step(tool_id: str, params: dict[str, Any]) -> ToolResult:
        if not registry.get(tool_id):
            raise ElliotError("TOOL_NOT_FOUND", f"Skill step references unknown tool: '{tool_id}'")
        return await executor.execute(tool_id, params)

    return await run_skill_steps(skill, inputs, _run_step)


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
    # Anything else is an authoring mistake, and silently resolving it to None
    # used to surface later as a baffling MISSING_PARAM on the step's tool.
    # Fail here instead, with the reference that didn't resolve and the exact
    # syntax that would (naming the caller's own value when we can see it).
    hint = (
        f"Did you mean '{{{{ skill.input.{path} }}}}'?"
        if len(parts) == 1 and (path in inputs or path.isidentifier())
        else "Use '{{ skill.input.<name> }}' for a skill input, or "
        "'{{ steps.<alias>.<field> }}' for a field of an earlier step's first row."
    )
    raise ElliotError(
        "SKILL_TEMPLATE_UNRESOLVED",
        f"Skill step parameter references '{{{{ {path} }}}}', which is not a valid binding. {hint}",
        detail={"reference": path, "declared_inputs": sorted(inputs)},
    )
