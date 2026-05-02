# 028 — Plugin Source + SQL Integration Tests

**Sprint**: 2 | **Estimate**: 3h | **Depends on**: 025

## Objective
Test the MCP plugin's source and SQL tools end-to-end using `InMemoryTransport` (no HTTP needed).

## Files to Create
- `packages/mcp-plugin/tests/integration/source-tools.test.ts`
- `packages/mcp-plugin/tests/integration/sql-tools.test.ts`

## Test Setup (both files)
```typescript
const session = new ElliotSession();
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
await createElliotServer(session).connect(serverTransport);
const client = new Client({ name: 'test', version: '0.0.1' });
await client.connect(clientTransport);
```

## Required Tests

**source-tools.test.ts:**
- `elliot_discover_source` with fixture CSV → returns schema with correct columns + row count
- `elliot_list_sources` after discover → returns 1 source
- `elliot_preview_source` → returns correct rows
- `elliot_profile_source` → returns column statistics
- `elliot_remove_source` → source gone from list, table dropped from schema

**sql-tools.test.ts:**
- `elliot_get_schema` → returns loaded table names
- `elliot_query_sql` with valid SELECT → returns rows
- `elliot_query_sql` with DROP → returns error content (not MCP protocol error)
- `elliot_validate_sql` → correct valid/invalid classification

## Done When
- [ ] All tests pass using `InMemoryTransport`
- [ ] No HTTP server needed to run tests
