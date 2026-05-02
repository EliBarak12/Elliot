# 016 — Tool + Skill Validator (Pydantic)

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 005, 010

## Files to Create

### `packages/core/src/elliot_core/tools/validator.py`
```python
from pydantic import ValidationError
from elliot_core.types.tool import ToolDefinition, SkillDefinition
from elliot_core.sqlite.query_runner import validate_tool_sql
from elliot_core.errors import ElliotError
import re

def validate_tool_definition(data: dict) -> ToolDefinition:
    """Parse + validate a tool definition dict. Raises ElliotError on failure."""
    try:
        tool = ToolDefinition.model_validate(data)
    except ValidationError as e:
        raise ElliotError("INVALID_TOOL", str(e))
    _validate_sql_params(tool)
    return tool

def _validate_sql_params(tool: ToolDefinition) -> None:
    """Check :param references match the parameters list."""
    sql_params = set(re.findall(r":([a-zA-Z_][a-zA-Z0-9_]*)", tool.sql))
    defined_params = {p.name for p in tool.parameters}
    missing = sql_params - defined_params
    if missing:
        raise ElliotError("INVALID_TOOL", f"SQL references undefined params: {missing}")
    unused = defined_params - sql_params
    if unused:
        # warning only — don't raise, just return info
        pass  # callers can check via validate_tool_sql_params separately

def validate_skill_definition(data: dict) -> SkillDefinition:
    try:
        return SkillDefinition.model_validate(data)
    except ValidationError as e:
        raise ElliotError("INVALID_SKILL", str(e))
```

## Done When
- [ ] Valid tool dict → returns `ToolDefinition`
- [ ] SQL with `:missing` not in parameters → raises `ElliotError`
- [ ] Tool name with spaces → Pydantic `ValidationError` → wrapped as `ElliotError`
- [ ] Tool description < 10 chars → `ElliotError`
