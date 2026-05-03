# 029 — Tool MCP Tools

**Sprint**: 2 | **Estimate**: 3h | **Depends on**: 028

## Files to Create

### `packages/mcp-plugin/src/elliot_mcp_plugin/tools/tool_tools.py`

```python
from mcp.server.fastmcp import FastMCP
from elliot_mcp_plugin.session import ElliotSession
from elliot_core.tools.validator import validate_tool_definition
from elliot_core.tools.executor import execute_tool
from elliot_core import ElliotError
import uuid

def register_tool_tools(mcp: FastMCP, session: ElliotSession) -> None:

    @mcp.tool()
    def elliot_create_tool(
        name: str, description: str, category: str,
        sql: str, parameters: list[dict]
    ) -> dict:
        """Define a new business tool backed by a SQL query."""
        try:
            tool = validate_tool_definition({
                "id": str(uuid.uuid4()), "name": name,
                "description": description, "category": category,
                "sql": sql, "parameters": parameters,
            })
            session.registry.add(tool)
            session.save()
            return {"tool_id": tool.id, "status": "created"}
        except ElliotError as e:
            return {"error": f"[{e.code}] {e.message}"}

    @mcp.tool()
    def elliot_update_tool(tool_id: str, patch: dict) -> dict:
        """Partially update a tool definition and re-validate."""
        ...

    @mcp.tool()
    def elliot_list_tools() -> dict:
        """List all defined tools with id, name, category, and description."""
        ...

    @mcp.tool()
    def elliot_get_tool(tool_id: str) -> dict:
        """Return the full definition of a tool."""
        ...

    @mcp.tool()
    def elliot_delete_tool(tool_id: str) -> dict:
        """Remove a tool from the registry."""
        ...

    @mcp.tool()
    def elliot_preview_tool(tool_id: str, params: dict) -> dict:
        """Execute a tool against current SQLite data and return rows."""
        try:
            tool = session.registry.get(tool_id)
            if not tool:
                raise ElliotError("TOOL_NOT_FOUND", tool_id)
            result = execute_tool(tool, params, session.engine)
            return result.model_dump()
        except ElliotError as e:
            return {"error": f"[{e.code}] {e.message}"}
```

## Done When
- [ ] `elliot_create_tool` → `elliot_get_tool` returns same definition
- [ ] `elliot_preview_tool` returns real rows from SQLite
- [ ] `elliot_delete_tool` removes from `elliot_list_tools`
