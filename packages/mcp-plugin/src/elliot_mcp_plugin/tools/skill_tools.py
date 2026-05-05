"""Skill management tools — define and execute multi-step skills."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from elliot_mcp_plugin.session import ElliotSession


def register_skill_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_list_skills() -> dict:  # type: ignore[type-arg]
        """List all skills currently defined in the session registry."""
        return {
            "skills": [
                {"id": s.id, "name": s.name, "steps": len(s.steps)}
                for s in session.registry.get_all_skills()
            ]
        }

    @mcp.tool()
    def elliot_run_skill(skill_id: str, inputs: dict) -> dict:  # type: ignore[type-arg]
        """Execute a multi-step skill by ID with the given input values."""
        import asyncio

        from elliot_core.errors import ElliotError
        from elliot_core.tools.executor import ToolExecutor
        from elliot_core.tools.skill_runner import execute_skill
        from elliot_core.types.connector import ConnectorConfig

        try:
            skill = session.registry.get_skill(skill_id)
            if not skill:
                return {"error": f"Skill '{skill_id}' not found"}
            config = ConnectorConfig(
                name="session",
                slug="session",
                version="0.1.0",
                sources=list(session.sources.values()),
                tools=session.registry.get_all(),
            )
            secrets = session.workspace.load_secrets()
            executor = ToolExecutor(config, secrets)
            result = asyncio.get_event_loop().run_until_complete(
                execute_skill(skill, inputs, session.registry, executor)
            )
            return {"rows": result.rows, "meta": result.meta}
        except ElliotError as exc:
            return {"error": f"[{exc.code}] {exc.message}"}
