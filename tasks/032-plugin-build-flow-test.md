# 032 — Plugin Full Build-Flow Integration Test

**Sprint**: 2 | **Estimate**: 2h | **Depends on**: 031

## Objective
End-to-end test of the entire plugin flow using `InMemoryTransport`: discover → build → export.

## Files to Create
- `packages/mcp-plugin/tests/integration/build-flow.test.ts`

## Test Scenario
```
1. elliot_set_product_context(name: 'TestCo', domain: 'e-commerce')
2. elliot_discover_source(type: 'file', config: { path: 'tests/fixtures/customers.csv' }, name: 'customers')
3. elliot_discover_source(type: 'file', config: { path: 'tests/fixtures/orders.json' }, name: 'orders')
4. elliot_create_tool({ name: 'get_customer', sql: 'SELECT * FROM customers WHERE id = :id', ... })
5. elliot_preview_tool('get_customer', { id: 'C001' }) → returns row
6. elliot_build_connector({ toolIds: [toolId], name: 'TestCo Connector', ... })
7. elliot_export_connector() → file exists at .elliot/connector.json
8. Read file, deserializeConnector() → valid ConnectorConfig with 1 tool
```

## Done When
- [ ] All 8 steps succeed
- [ ] Exported connector deserializes without error
- [ ] `pnpm --filter @elliot/mcp-plugin test` exits 0 with coverage ≥ 85%
