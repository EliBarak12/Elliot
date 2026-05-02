# 007 — JSON Flattener

**Sprint**: 1 | **Estimate**: 4h | **Depends on**: 006

## Objective
The core algorithm that turns arbitrary nested JSON into flat SQLite-ready tables.

## Files to Create

### `packages/core/src/sqlite/flattener.ts`

Export: `flatten(data: unknown[], tableName: string): FlattenResult`

**Rules (implement all):**
1. Primitive field → column in current table
2. Nested object → flatten inline with `parent_child` key (underscore separator)
3. Array of primitives → serialize entire array as JSON TEXT column
4. Array of objects → create child table named `<parent>_<key>`, add `_parent_id` INTEGER FK, add `_index` INTEGER column
5. Nesting depth > 5 → serialize as TEXT, emit `FlattenWarning` with `type: 'depth_exceeded'`
6. Circular reference (detected via `WeakSet`) → serialize as TEXT `"[Circular]"`, emit warning
7. Boolean → INTEGER (0 or 1)
8. `null` / `undefined` → NULL
9. Integer > `Number.MAX_SAFE_INTEGER` → TEXT
10. Column names → run through `safeName()` + `deduplicateNames()`
11. Array length > 1000 → truncate to 1000 rows, emit `FlattenWarning` with `type: 'array_truncated'`
12. Empty array → create empty child table (schema only, zero rows)

**Output:** `FlattenResult` with `primaryTable: FlattenedTable` and `relatedTables: FlattenedTable[]`

## Done When
- [ ] Handles all 12 rules above
- [ ] Returns correct `FlattenWarning[]` for depth, circular, truncation
- [ ] Zero `any` types
