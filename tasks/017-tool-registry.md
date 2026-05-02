# 017 — Tool Registry

**Sprint**: 1 | **Estimate**: 1h | **Depends on**: 016

## Files to Create

### `packages/core/src/elliot_core/tools/registry.py`
```python
from elliot_core.types.tool import ToolDefinition, SkillDefinition
from elliot_core.errors import ElliotError

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._skills: dict[str, SkillDefinition] = {}

    def add(self, tool: ToolDefinition) -> None:
        if any(t.name == tool.name for t in self._tools.values() if t.id != tool.id):
            raise ElliotError("TOOL_NAME_CONFLICT", f"Tool name already exists: {tool.name}")
        self._tools[tool.id] = tool

    def update(self, tool_id: str, patch: dict) -> ToolDefinition:
        existing = self.get(tool_id)
        if not existing:
            raise ElliotError("TOOL_NOT_FOUND", f"Tool not found: {tool_id}")
        merged = existing.model_dump() | patch
        updated = ToolDefinition.model_validate(merged)
        self._tools[tool_id] = updated
        return updated

    def delete(self, tool_id: str) -> None:
        self._tools.pop(tool_id, None)

    def get(self, tool_id: str) -> ToolDefinition | None:
        return self._tools.get(tool_id)

    def get_by_name(self, name: str) -> ToolDefinition | None:
        return next((t for t in self._tools.values() if t.name == name), None)

    def get_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    # Same pattern for skills
    def add_skill(self, skill: SkillDefinition) -> None: ...
    def get_all_skills(self) -> list[SkillDefinition]: ...
    def get_skill(self, skill_id: str) -> SkillDefinition | None: ...
    def delete_skill(self, skill_id: str) -> None: ...
    def clear(self) -> None:
        self._tools.clear()
        self._skills.clear()
```

## Done When
- [ ] Adding duplicate name raises `ElliotError("TOOL_NAME_CONFLICT")`
- [ ] `update()` merges partial dict and re-validates
- [ ] `get_all()` preserves insertion order
