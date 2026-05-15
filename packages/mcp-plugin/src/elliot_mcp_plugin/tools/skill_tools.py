"""Skill management tools — define and execute multi-step skills."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.tools.skill_runner import execute_skill
from elliot_core.tools.validator import validate_skill_definition
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)

_STEP_PARAMS_ALIASES = ("params", "arguments", "args", "parameters", "inputs")


def _normalize_skill_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept the loose shapes agents naturally produce for skill steps.

    A SkillStep requires {alias, tool_id, params}. Common alternative keys
    seen from agents: `arguments`, `args`, `parameters`, `inputs` (instead of
    `params`); `tool` (instead of `tool_id`). Normalize before validation so
    the error surfaced to the agent is about *real* problems, not key naming.
    """
    if not isinstance(steps, list):
        raise ElliotError(
            "INVALID_SKILL",
            "Skill 'steps' must be a list of step dicts, each with {alias, tool_id, params}.",
        )
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(steps):
        if not isinstance(raw, dict):
            raise ElliotError(
                "INVALID_SKILL",
                f"Step at index {index} must be an object with {{alias, tool_id, params}}.",
            )
        step = dict(raw)
        if "tool_id" not in step and "tool" in step:
            step["tool_id"] = step.pop("tool")
        if "params" not in step:
            for alt in _STEP_PARAMS_ALIASES[1:]:
                if alt in step:
                    step["params"] = step.pop(alt)
                    break
        step.setdefault("params", {})

        missing = [k for k in ("alias", "tool_id") if not step.get(k)]
        if missing:
            raise ElliotError(
                "INVALID_SKILL",
                (
                    f"Step at index {index} is missing required field(s): "
                    f"{', '.join(missing)}. Each step needs "
                    "{alias: str, tool_id: str, params: dict}."
                ),
                detail={"index": index, "missing": missing, "received": list(raw)},
            )
        normalized.append(step)
    return normalized


def register_skill_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_create_skill(
        name: str,
        description: str,
        steps: list[dict],  # type: ignore[type-arg]
        input_parameters: list[dict],  # type: ignore[type-arg]
    ) -> dict:  # type: ignore[type-arg]
        """Define a multi-step skill that chains tool calls together.

        Each step requires {alias: str, tool_id: str, params: dict}. The keys
        `arguments`, `args`, `parameters`, and `inputs` are accepted as
        aliases for `params`; `tool` is accepted as an alias for `tool_id`.
        """
        try:
            skill_id = str(uuid.uuid4()).replace("-", "_")
            normalized_steps = _normalize_skill_steps(steps)
            skill = validate_skill_definition(
                {
                    "id": skill_id,
                    "name": name,
                    "description": description,
                    "steps": normalized_steps,
                    "input_parameters": input_parameters,
                }
            )
            for step in skill.steps:
                if not session.registry.get(step.tool_id):
                    raise ElliotError(
                        "TOOL_NOT_FOUND",
                        f"Step '{step.alias}' references unknown tool: '{step.tool_id}'",
                    )
            session.registry.add_skill(skill)
            session.save()
            log.info("skill.created", skill_id=skill.id)
            return {"skill_id": skill.id, "status": "created"}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("skill.create.failed", error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_list_skills() -> dict:  # type: ignore[type-arg]
        """List all defined skills with their full definitions.

        Each entry includes id, name, description, steps, and input_parameters
        so the Studio and any other client can render the skill without an
        extra elliot_get_skill round-trip. The convenience field step_count
        is also included for clients that only need a summary.
        """
        try:
            # Pick up skills the agent created since our last list — even
            # if the agent runs in a separate plugin process sharing the
            # same workspace.
            session.refresh_from_disk()
            return {
                "skills": [
                    {**s.model_dump(), "step_count": len(s.steps)}
                    for s in session.registry.get_all_skills()
                ],
                "count": len(session.registry.get_all_skills()),
            }
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_get_skill(skill_id: str) -> dict:  # type: ignore[type-arg]
        """Return the full definition of a skill."""
        try:
            skill = session.registry.get_skill(skill_id)
            if skill is None:
                return {"error": f"Skill not found: {skill_id}"}
            return skill.model_dump()
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    async def elliot_preview_skill(
        skill_id: str,
        inputs: dict | None = None,  # type: ignore[type-arg]
        arguments: dict | None = None,  # type: ignore[type-arg]
        params: dict | None = None,  # type: ignore[type-arg]
    ) -> dict:  # type: ignore[type-arg]
        """Execute all skill steps against session SQLite data and return the final result.

        Pass skill input values via 'inputs' (preferred), 'arguments', or 'params'.
        """
        try:
            skill = session.registry.get_skill(skill_id)
            if skill is None:
                return {"error": f"Skill not found: {skill_id}"}

            supplied: dict[str, Any] = {}
            for src in (inputs, arguments, params):
                if src:
                    supplied.update(src)

            from elliot_core.tools.executor import ToolExecutor
            from elliot_core.types.connector import ConnectorConfig

            # Inject SQL stored alongside each session tool into the ToolDefinition
            # so the executor can run it instead of an empty filter_groups SELECT.
            tools_with_sql = [
                t.model_copy(update={"sql": session.tool_sql[t.id]})
                if t.id in session.tool_sql
                else t
                for t in session.registry.get_all()
            ]

            config = ConnectorConfig(
                name="session",
                slug="session",
                version="0.1.0",
                sources=list(session.sources.values()),
                tools=tools_with_sql,
            )
            secrets = session.workspace.load_secrets()
            executor = ToolExecutor(config, secrets)
            result = await execute_skill(skill, supplied, session.registry, executor)
            return {"rows": result.rows, "meta": result.meta}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("skill.preview.failed", skill_id=skill_id, error=str(exc))
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_delete_skill(skill_id: str) -> dict:  # type: ignore[type-arg]
        """Remove a skill from the registry."""
        try:
            if session.registry.get_skill(skill_id) is None:
                return {"error": f"Skill not found: {skill_id}"}
            session.registry.delete_skill(skill_id)
            session.save()
            log.info("skill.deleted", skill_id=skill_id)
            return {"status": "deleted", "skill_id": skill_id}
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))
