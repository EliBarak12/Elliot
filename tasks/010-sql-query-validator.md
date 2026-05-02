# 010 — SQL Query Validator

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 009

## Objective
Prevent SQL injection and DDL execution. Every tool-defined SQL goes through this before running.

## Files to Create

### `packages/core/src/sqlite/query-runner.ts`

**`validateToolSql(sql: string): { valid: true } | { valid: false; reason: string }`**

Rejection rules (all must be enforced):
1. After trimming whitespace + stripping `--` comments, must start with `SELECT`
2. Contains any of: `DROP`, `CREATE`, `ALTER`, `INSERT`, `UPDATE`, `DELETE`, `ATTACH`, `DETACH`, `PRAGMA` → reject
3. Contains `;` anywhere (multiple statements) → reject
4. Empty or whitespace-only → reject

**`runToolQuery(db: SQLiteEngine, sql: string, params: Record<string, unknown>): Record<string, unknown>[]`**
- Validate first, throw `ElliotError('INVALID_SQL', ...)` if invalid
- Bind named params (`:paramName` syntax) via `better-sqlite3`
- Return rows

## Done When
- [ ] `SELECT * FROM users` → valid
- [ ] `DROP TABLE users` → rejected
- [ ] `SELECT 1; DROP TABLE users` → rejected (semicolon)
- [ ] `SELECT * FROM users -- ; DROP TABLE users` → valid (comment stripped)
- [ ] `PRAGMA table_info(users)` → rejected
