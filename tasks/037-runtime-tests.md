# 037 — Runtime Integration Tests

**Sprint**: 3 | **Estimate**: 3h | **Depends on**: 036

## Objective
End-to-end tests for the connector runtime: load connector, call tools via MCP, verify audit + cache.

## Files to Create
- `packages/connector-runtime/tests/fixtures/test-connector.json`
- `packages/connector-runtime/tests/integration/runtime.test.ts`

## Fixture
`test-connector.json` — a valid `ConnectorConfig` with:
- 1 file source pointing to `packages/core/tests/fixtures/customers.csv`
- 2 tools: `list_customers` (no params) and `get_customer` (param: `id`)

## Required Tests
1. Load fixture connector → `tools/list` returns 2 tools
2. `tools/call` with `list_customers` → returns rows from CSV
3. `tools/call` with `get_customer({ id: 'C001' })` → returns 1 row
4. Call same tool twice → second call uses cache (mock fetch not called twice)
5. Rate limit: call tool > 60 times in quick succession → `RATE_LIMIT_EXCEEDED` error
6. `audit.ndjson` has one entry per successful call
7. Unknown tool name → `TOOL_NOT_FOUND` error content

## Done When
- [ ] All 7 tests pass
- [ ] `pnpm --filter @elliot/connector-runtime test` exits 0
- [ ] Coverage ≥ 85%
