# 031 — Context + Connector MCP Tools

**Sprint**: 2 | **Estimate**: 3h | **Depends on**: 030

## Files to Create

### `packages/mcp-plugin/src/elliot_mcp_plugin/tools/context_tools.py`
```python
def register_context_tools(mcp: FastMCP, session: ElliotSession) -> None:

    @mcp.tool()
    def elliot_set_product_context(
        name: str, domain: str, description: str = "", audience: str = ""
    ) -> dict:
        """Set context about the product being connected."""
        from elliot_core.types.connector import ProductContext
        session.product_context = ProductContext(name=name, domain=domain, description=description, audience=audience)
        session.save()
        return {"status": "ok"}

    @mcp.tool()
    def elliot_get_session_state() -> dict:
        """Return a summary of current session: sources, tools, skills, connector status."""
        return {
            "source_count": len(session.sources),
            "tool_count": len(session.registry.get_all()),
            "skill_count": len(session.registry.get_all_skills()),
            "product_context": session.product_context.model_dump() if session.product_context else None,
            "runtime_running": session.runtime_process is not None and session.runtime_process.poll() is None,
        }
```

### `packages/mcp-plugin/src/elliot_mcp_plugin/tools/connector_tools.py`
```python
def register_connector_tools(mcp: FastMCP, session: ElliotSession) -> None:

    @mcp.tool()
    def elliot_build_connector(
        tool_ids: list[str], skill_ids: list[str],
        name: str, version: str, slug: str
    ) -> dict:
        """Assemble a ConnectorConfig from selected tools and skills."""
        ...

    @mcp.tool()
    def elliot_export_connector(path: str = ".elliot/connector.json") -> dict:
        """Write the built ConnectorConfig to disk as JSON."""
        ...

    @mcp.tool()
    def elliot_start_runtime(port: int = 3001) -> dict:
        """Start the connector runtime as a subprocess on the given port."""
        import subprocess
        session.runtime_process = subprocess.Popen([
            "uv", "run", "uvicorn",
            "elliot_connector_runtime.main:app",
            f"--port={port}",
            "--app-dir=packages/connector-runtime/src",
        ])
        return {"url": f"http://localhost:{port}/mcp", "pid": session.runtime_process.pid}

    @mcp.tool()
    def elliot_stop_runtime() -> dict:
        """Stop the running connector runtime process."""
        if session.runtime_process:
            session.runtime_process.terminate()
            session.runtime_process = None
        return {"status": "stopped"}

    @mcp.tool()
    def elliot_get_connection_config() -> dict:
        """Return the MCP config snippet to add to an agent's config."""
        return {"type": "http", "url": "http://localhost:3001/mcp"}
```

## Done When
- [ ] `elliot_build_connector` → `elliot_export_connector` → file readable, valid JSON
- [ ] `elliot_get_connection_config` returns correct structure
