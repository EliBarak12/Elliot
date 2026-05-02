# 014 — DB Connector

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 005

## Objective
Read data from local SQLite files and PostgreSQL databases using read-only connections.

## Files to Create

### `packages/core/src/sources/db-connector.ts`

**`queryDatabase(config: DbSourceConfig, secrets: Record<string, string>): Promise<FetchResult>`**

Supported DB types:
- **`sqlite`** — open file with `better-sqlite3` in read-only mode (`{ readonly: true }`), execute `config.sql`, return rows
- **`postgres`** — connect with `pg` package using connection string from secrets, execute `config.sql` as read-only transaction (`BEGIN READ ONLY`), return rows, close connection

Safety rules:
- Only `SELECT` queries allowed — validate with `validateToolSql()` before executing
- PostgreSQL: set `statement_timeout = 30000` (30s)
- Never log connection strings

### `packages/core/src/sources/schema-detector.ts`
- `detectSchema(rows: unknown[]): ColumnMeta[]` — sample first 100 rows, infer type per column using `inferColumnType()`
- `schemaFingerprint(cols: ColumnMeta[]): string` — stable hash (SHA-256) of sorted column names + types, for drift detection

## Done When
- [ ] SQLite file read-only query returns correct rows
- [ ] Non-SELECT query rejected before execution
- [ ] `schemaFingerprint` is stable across calls with same schema
