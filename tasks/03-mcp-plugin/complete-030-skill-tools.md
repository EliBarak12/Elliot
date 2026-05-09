# 030 — Skill MCP Tools

**Sprint**: 2 | **Estimate**: 2h | **Depends on**: 029

## Files to Create

### `packages/mcp-plugin/src/elliot_mcp_plugin/tools/skill_tools.py`

```python
from mcp.server.fastmcp import FastMCP
from elliot_mcp_plugin.session import ElliotSession
from elliot_core.tools.validator import validate_skill_definition
from elliot_core.tools.skill_runner import execute_skill
from elliot_core import ElliotError
import uuid

def register_skill_tools(mcp: FastMCP, session: ElliotSession) -> None:

    @mcp.tool()
    def elliot_create_skill(
        name: str, description: str,
        steps: list[dict], input_parameters: list[dict]
    ) -> dict:
        """Define a multi-step skill that chains tool calls together."""
        try:
            skill = validate_skill_definition({
                "id": str(uuid.uuid4()), "name": name,
                "description": description, "steps": steps,
                "input_parameters": input_parameters,
            })
            for step in skill.steps:
                if not session.registry.get_by_name(step.tool_name):
                    raise ElliotError("TOOL_NOT_FOUND", f"Step references unknown tool: {step.tool_name}")
            session.registry.add_skill(skill)
            session.save()
            return {"skill_id": skill.id, "status": "created"}
        except ElliotError as e:
            return {"error": f"[{e.code}] {e.message}"}

    @mcp.tool()
    def elliot_list_skills() -> dict:
        """List all defined skills."""
        return {"skills": [s.model_dump() for s in session.registry.get_all_skills()]}

    @mcp.tool()
    def elliot_get_skill(skill_id: str) -> dict:
        """Return the full definition of a skill."""
        ...

    @mcp.tool()
    def elliot_preview_skill(skill_id: str, inputs: dict) -> dict:
        """Execute all skill steps and return the final result."""
        try:
            skill = session.registry.get_skill(skill_id)
            if not skill:
                raise ElliotError("TOOL_NOT_FOUND", skill_id)
            result = execute_skill(skill, inputs, session.registry, session.engine)
            return result.model_dump()
        except ElliotError as e:
            return {"error": f"[{e.code}] {e.message}"}

    @mcp.tool()
    def elliot_delete_skill(skill_id: str) -> dict:
        """Remove a skill from the registry."""
        ...
```

## Done When
- [ ] `elliot_create_skill` with non-existent `tool_name` in a step → `{"error": ...}`
- [ ] `elliot_preview_skill` runs all steps and returns final result
