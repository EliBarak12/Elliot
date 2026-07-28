"""Skill management tools — define and execute multi-step skills."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.naming import is_valid_identifier, slugify_identifier
from elliot_core.tools.skill_runner import execute_skill
from elliot_core.tools.validator import validate_skill_definition
from elliot_mcp_plugin.build_state import refresh_built_connector
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
        steps: list[dict] | None = None,  # type: ignore[type-arg]
        input_parameters: list[dict] | None = None,  # type: ignore[type-arg]
        instructions: str = "",
        when_to_use: str = "",
    ) -> dict:  # type: ignore[type-arg]
        """Define a connector skill — a workflow around the connector's tools.

        A skill comes in two flavours, and may be both:

        - **Deterministic**: pass `steps`, a chain the runtime executes
          end-to-end. Each step is {alias: str, tool_id: str, params: dict}.
          The keys `arguments`, `args`, `parameters`, and `inputs` are accepted
          as aliases for `params`; `tool` is accepted for `tool_id`.
        - **Prose**: pass `instructions` (markdown) and optionally `when_to_use`
          to describe a workflow the agent drives itself — including branches a
          flat step chain can't express. This is exported as a SKILL.md guide,
          the same way Elliot ships its own skills.

        Step param binding — a step's params are static values, or templates
        resolved at run time:

        - `"{{ skill.input.NAME }}"` — the caller-supplied input NAME declared
          in `input_parameters`. Bare `"{{ NAME }}"` does NOT work.
        - `"{{ steps.ALIAS.FIELD }}"` — FIELD from the first result row of the
          earlier step ALIAS (chain a lookup step into the next step).
        - Templates also interpolate inside strings: `"user_{{ skill.input.id }}"`.

        Example: steps=[{alias: "user", tool_id: "find_user",
        params: {"email": "{{ skill.input.email }}"}}, {alias: "orders",
        tool_id: "list_orders", params: {"user_id": "{{ steps.user.id }}"}}]
        with input_parameters=[{name: "email", type: "string", required: true}].

        Supply at least one of `steps` or `instructions`.
        """
        try:
            # Derive a readable snake_case id from the name (matching tool ids)
            # instead of an opaque UUID. Fall back to a uuid-suffixed slug only
            # when the name yields nothing usable, and disambiguate collisions.
            slug = slugify_identifier(name)
            if not slug:
                slug = "skill_" + uuid.uuid4().hex[:8]
            elif not is_valid_identifier(slug):
                slug = f"s_{slug}"
            # Same name → UPDATE the existing skill in place. The old behaviour
            # silently minted `_2` / `_3` duplicates (LIVE_QA F3), leaving
            # agents guessing which copy is real and no way to fix a skill.
            skill_id = slug
            existing = session.registry.get_skill(skill_id)
            normalized_steps = _normalize_skill_steps(steps or [])
            skill = validate_skill_definition(
                {
                    "id": skill_id,
                    "name": name,
                    "description": description,
                    "steps": normalized_steps,
                    "input_parameters": input_parameters or [],
                    "instructions": instructions,
                    "when_to_use": when_to_use,
                }
            )
            for step in skill.steps:
                if not session.registry.get(step.tool_id):
                    raise ElliotError(
                        "TOOL_NOT_FOUND",
                        f"Step '{step.alias}' references unknown tool: '{step.tool_id}'",
                    )
            session.registry.add_skill(skill)
            refresh_built_connector(session)
            session.save()
            # Surface the new skill as an MCP prompt immediately so it shows up
            # in prompts/list without a server restart (F-027). Best-effort: a
            # prompt-registration hiccup must not fail skill creation.
            try:
                from elliot_mcp_plugin.prompts import register_session_skill_prompt

                register_session_skill_prompt(mcp, skill)
            except Exception:
                log.warning("skill.prompt.register_failed", skill_id=skill.id, exc_info=True)
            status = "updated" if existing else "created"
            log.info("skill.saved", skill_id=skill.id, status=status)
            return {"skill_id": skill.id, "status": status}
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

            # Prose-only skills have nothing to execute — they're guidance the
            # agent follows itself. Return that guidance instead of an empty set
            # so the caller sees the skill rather than a confusing no-op result.
            if not skill.steps:
                return {
                    "rows": [],
                    "meta": {
                        "kind": "prose",
                        "when_to_use": skill.when_to_use,
                        "instructions": skill.instructions,
                    },
                }

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
            refresh_built_connector(session)
            session.save()
            log.info("skill.deleted", skill_id=skill_id)
            return {"status": "deleted", "skill_id": skill_id}
        except Exception as exc:
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))
