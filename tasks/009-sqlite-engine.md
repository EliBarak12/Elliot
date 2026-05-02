# 009 — SQLiteEngine Class

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 007

## Objective
In-memory SQLite database wrapper using `better-sqlite3`. Synchronous API — no async/await anywhere.

## Files to Create

### `packages/core/src/sqlite/engine.ts`

**Class `SQLiteEngine`:**
- `constructor()` — opens `:memory:` DB, sets `WAL` journal mode and `foreign_keys = ON`
- `loadTable(table: FlattenedTable): void` — DROP IF EXISTS + CREATE TABLE + batch INSERT in a transaction
- `loadResult(result: FlattenResult): void` — load primary + all related tables
- `query(sql: string, params?: Record<string, unknown>): Record<string, unknown>[]`
- `getTableNames(): string[]`
- `getTableSchema(tableName: string): { name: string; type: string; notnull: number }[]`
- `getTableStats(tableName: string): { rowCount: number }` 
- `profileColumn(tableName: string, col: string): { min: unknown; max: unknown; nullCount: number; distinctCount: number; topValues: unknown[] }`
- `close(): void`

**All methods are synchronous.** `better-sqlite3` is synchronous by design.

## Done When
- [ ] Can load a `FlattenResult` and query it back with correct rows
- [ ] `profileColumn` returns accurate stats
- [ ] Zero async/await in the implementation
