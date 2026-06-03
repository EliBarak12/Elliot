# 023 — MCP Server Factory (FastMCP)

**Sprint**: 2 | **Estimate**: 2h | **Depends on**: 022

## Objective
Factory that creates a configured `FastMCP` instance with all tool groups registered.

## Files to Create

### `packages/mcp-plugin/src/elliot_mcp_plugin/server.py`
```python
from mcp.server.fastmcp import FastMCP
from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.tools.source_tools import register_source_tools
from elliot_mcp_plugin.tools.sql_tools import register_sql_tools
from elliot_mcp_plugin.tools.tool_tools import register_tool_tools
from elliot_mcp_plugin.tools.skill_tools import register_skill_tools
from elliot_mcp_plugin.tools.context_tools import register_context_tools
from elliot_mcp_plugin.tools.connector_tools import register_connector_tools
from elliot_mcp_plugin.tools.studio_tools import register_studio_tools

def create_elliot_server(session: ElliotSession) -> FastMCP:
    mcp = FastMCP("elliot")
    register_source_tools(mcp, session)
    register_sql_tools(mcp, session)
    register_tool_tools(mcp, session)
    register_skill_tools(mcp, session)
    register_context_tools(mcp, session)
    register_connector_tools(mcp, session)
    register_studio_tools(mcp, session)
    return mcp
```

**Pattern for each `register_*` function:**
```python
def register_source_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_discover_source(source_type: str, config: dict, name: str) -> dict:
        """Fetch a data source and load it into in-memory SQLite."""
        try:
            # ... logic using session ...
            return {"status": "ok", "schema": ...}
        except ElliotError as e:
            return {"error": f"[{e.code}] {e.message}"}
```

## Done When
- [ ] `create_elliot_server(session)` returns a `FastMCP` instance without error
- [ ] Calling `mcp.list_tools()` includes tools from all groups
