# 011 — SQLite Unit + Integration Tests

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 010

## Objective
Test the SQLiteEngine and query validator thoroughly, including a multi-table JOIN integration test.

## Files to Create
- `packages/core/tests/unit/engine.test.ts`
- `packages/core/tests/unit/query-runner.test.ts`
- `packages/core/tests/integration/sqlite-engine.test.ts`

## Required Test Cases

**engine.test.ts:**
- Load table → query returns correct rows
- Parameterized query returns filtered rows
- Empty table → `[]`
- `getTableSchema` returns correct column types
- `profileColumn` returns accurate min/max/nullCount/distinctCount
- `close()` → subsequent query throws

**query-runner.test.ts:**
- Valid SELECT → passes
- `DROP TABLE` → rejected with reason
- Multiple statements (`;`) → rejected
- `PRAGMA` → rejected
- Comment injection (`-- DROP TABLE`) → valid (comment is safe)
- Named params bound correctly
- Missing required param → error

**sqlite-engine.test.ts (integration):**
- Load 3 related tables (customers, orders, products)
- Run 3-table JOIN query
- Run aggregate query (SUM, COUNT, GROUP BY)
- Run query with multiple named params

## Done When
- [ ] All tests pass
- [ ] SQL injection attempts all rejected
