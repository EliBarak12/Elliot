"""Skill management tools — define and execute multi-step skills."""

from __future__ import annotations

import asyncio
import uuid

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.tools.skill_runner import execute_skill
from elliot_core.tools.validator import validate_skill_definition
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)


def register_skill_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_create_skill(
        name: str,
        description: str,
        steps: list[dict],  # type: ignore[type-arg]
        input_parameters: list[dict],  # type: ignore[type-arg]
    ) -> dict:  # type: ignore[type-arg]
        """Define a multi-step skill that chains tool calls together."""
        try:
            skill_id = str(uuid.uuid4()).replace("-", "_")
            skill = validate_skill_definition(
                {
                    "id": skill_id,
                    "name": name,
                    "description": description,
                    "steps": steps,
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
        """List all defined skills with id, name, and step count."""
        try:
            return {
                "skills": [
                    {"id": s.id, "name": s.name, "step_count": len(s.steps)}
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
    def elliot_preview_skill(skill_id: str, inputs: dict) -> dict:  # type: ignore[type-arg]
        """Execute all skill steps against session SQLite data and return the final result."""
        try:
            skill = session.registry.get_skill(skill_id)
            if skill is None:
                return {"error": f"Skill not found: {skill_id}"}

            from elliot_core.tools.executor import ToolExecutor
            from elliot_core.types.connector import ConnectorConfig

            config = ConnectorConfig(
                name="session",
                slug="session",
                version="0.1.0",
                sources=list(session.sources.values()),
                tools=session.registry.get_all(),
            )
            secrets = session.workspace.load_secrets()
            executor = ToolExecutor(config, secrets)
            result = asyncio.run(execute_skill(skill, inputs or {}, session.registry, executor))
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
