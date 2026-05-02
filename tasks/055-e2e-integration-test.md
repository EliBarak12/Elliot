# 055 — End-to-End Integration Test

**Sprint**: 4 | **Estimate**: 3h | **Depends on**: 037, 032

## Objective
Single test that exercises the complete Phase 1 flow from source discovery to live tool call via the runtime.

## Files to Create
- `packages/mcp-plugin/tests/integration/e2e-flow.test.ts`

## Test Scenario (all via `InMemoryTransport`)
```
1. Create ElliotSession
2. Connect MCP client to plugin server
3. Call elliot_discover_source (CSV fixture) → assert schema returned
4. Call elliot_query_sql('SELECT COUNT(*) as n FROM customers') → assert n > 0
5. Call elliot_create_tool({ name: 'count_customers', sql: 'SELECT COUNT(*) as total FROM customers', ... })
6. Call elliot_preview_tool('count_customers', {}) → assert total > 0
7. Call elliot_build_connector({ toolIds: [toolId], name: 'E2E Connector', ... })
8. Call elliot_export_connector() → assert file exists
9. Load exported connector into RuntimeContext
10. Execute tool via connector runtime executor → assert same result as step 6
11. Assert audit.ndjson has 1 entry from step 10
```

## Done When
- [ ] All 11 steps pass
- [ ] Test runs in CI without any external services
- [ ] Full flow completes in < 10 seconds
