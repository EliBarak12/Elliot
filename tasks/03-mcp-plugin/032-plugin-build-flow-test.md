# 032 — Plugin Full Build-Flow Integration Test

**Sprint**: 2 | **Estimate**: 2h | **Depends on**: 031

## Files to Create
- `packages/mcp-plugin/tests/integration/test_build_flow.py`

## Test Scenario
```python
def test_full_build_flow(session, tmp_path):
    from elliot_mcp_plugin.tools.context_tools import _set_product_context
    from elliot_mcp_plugin.tools.source_tools import _discover_source
    from elliot_mcp_plugin.tools.tool_tools import _create_tool, _preview_tool
    from elliot_mcp_plugin.tools.connector_tools import _build_connector, _export_connector
    from elliot_core.connector.serializer import deserialize_connector

    # 1. Set context
    _set_product_context(session, name="TestCo", domain="e-commerce")

    # 2. Discover CSV source
    r = _discover_source(session, source_type="file",
                         config={"path": "packages/core/tests/fixtures/customers.csv"},
                         name="customers")
    assert "source_id" in r

    # 3. Create tool
    r = _create_tool(session, name="count_customers",
                     description="Returns the total number of customers",
                     category="AGGREGATE",
                     sql="SELECT COUNT(*) as total FROM customers",
                     parameters=[])
    tool_id = r["tool_id"]

    # 4. Preview tool
    r = _preview_tool(session, tool_id=tool_id, params={})
    assert r["rows"][0]["total"] > 0

    # 5. Build connector
    _build_connector(session, tool_ids=[tool_id], skill_ids=[],
                     name="TestCo Connector", version="1.0.0", slug="testco")

    # 6. Export
    export_path = str(tmp_path / "connector.json")
    _export_connector(session, path=export_path)

    # 7. Verify exported file
    import json
    config = deserialize_connector(open(export_path).read())
    assert len(config.tools) == 1
    assert config.tools[0].name == "count_customers"
```

## Done When
- [ ] All 7 assertions pass
- [ ] `uv run pytest packages/mcp-plugin/tests/ -v` exits 0
- [ ] Coverage ≥ 85% on `elliot_mcp_plugin`
