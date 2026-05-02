# 021 — Core Public API + Coverage

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 019, 020

## Objective
Expose a clean public API from `elliot_core` and ensure coverage ≥ 85%.

## Files to Create / Modify

### `packages/core/src/elliot_core/__init__.py`
```python
from elliot_core.types.source import SourceConfig, ApiEndpointConfig, AuthConfig, FetchResult
from elliot_core.types.tool import ToolDefinition, SkillDefinition, ToolResult, ParameterDefinition
from elliot_core.types.connector import ConnectorConfig, ProductContext
from elliot_core.types.sqlite import FlattenResult, FlattenedTable
from elliot_core.types.audit import AuditLogEntry
from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.sqlite.flattener import flatten
from elliot_core.tools.registry import ToolRegistry
from elliot_core.tools.executor import execute_tool
from elliot_core.tools.skill_runner import execute_skill
from elliot_core.connector.builder import ConnectorBuilder
from elliot_core.connector.serializer import serialize_connector, deserialize_connector
from elliot_core.connector.schema_gen import to_mcp_tool_schema
from elliot_core.workspace.store import WorkspaceStore
from elliot_core.errors import ElliotError

__all__ = [
    "SourceConfig", "ApiEndpointConfig", "AuthConfig", "FetchResult",
    "ToolDefinition", "SkillDefinition", "ToolResult", "ParameterDefinition",
    "ConnectorConfig", "ProductContext",
    "FlattenResult", "FlattenedTable",
    "AuditLogEntry",
    "SQLiteEngine", "flatten",
    "ToolRegistry", "execute_tool", "execute_skill",
    "ConnectorBuilder", "serialize_connector", "deserialize_connector", "to_mcp_tool_schema",
    "WorkspaceStore", "ElliotError",
]
```

### Remaining unit tests to write for coverage:
- `packages/core/tests/unit/test_executor.py` — tool execution edge cases
- `packages/core/tests/unit/test_skill_runner.py` — binding resolution
- `packages/core/tests/unit/test_connector_builder.py` — build + serialize round-trip

### Add coverage config to root `pyproject.toml`:
```toml
[tool.pytest.ini_options]
addopts = "--tb=short -q --cov=packages/core/src --cov-report=term-missing --cov-fail-under=85"
```

## Done When
- [ ] `from elliot_core import SQLiteEngine, ToolRegistry` works
- [ ] `uv run pytest --cov` exits 0 with ≥ 85% line coverage on `elliot_core`
