# 006 — Column Namer + Type Inferrer

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 005

## Objective
Two small utilities used by the JSON flattener: safe SQL column naming and type inference from sample values.

## Files to Create

### `packages/core/src/sqlite/column-namer.ts`
- `safeName(raw: string): string` — lowercase, replace non-alphanumeric with `_`, strip leading digits, append `_col` if SQL reserved keyword
- Reserved keywords list: `SELECT`, `FROM`, `WHERE`, `GROUP`, `ORDER`, `LIMIT`, `INDEX`, `TABLE`, `CREATE`, `DROP`, `INSERT`, `UPDATE`, `DELETE`, `JOIN`, `ON`, `AS`, `BY`, `AND`, `OR`, `NOT`, `NULL`, `IS`, `IN`
- `deduplicateNames(names: string[]): string[]` — append `_2`, `_3`, etc. for collisions

### `packages/core/src/sqlite/type-inferrer.ts`
- `inferColumnType(samples: unknown[]): SqliteColumnType` — majority vote across sample values
- Rules: all integers → INTEGER; any float → REAL; boolean → INTEGER (0/1); null-only → TEXT; mixed → TEXT
- `detectFormat(value: string): 'iso_date' | 'uuid' | 'email' | 'boolean_string' | null`

## Done When
- [ ] `safeName('from')` returns `'from_col'`
- [ ] `safeName('user-id')` returns `'user_id'`
- [ ] `inferColumnType([1, 2, 3])` returns `'INTEGER'`
- [ ] `inferColumnType([1.5, 2])` returns `'REAL'`
- [ ] `inferColumnType([true, false])` returns `'INTEGER'`
