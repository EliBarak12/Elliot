# 008 — Flattener Unit Tests

**Sprint**: 1 | **Estimate**: 3h | **Depends on**: 007

## Objective
Exhaustive test suite for the JSON flattener. Must cover every documented edge case.

## Files to Create
- `packages/core/tests/unit/flattener.test.ts`
- `packages/core/tests/unit/column-namer.test.ts`
- `packages/core/tests/unit/type-inferrer.test.ts`

## Required Test Cases (flattener.test.ts — minimum 15)
1. Flat array of objects → single table, correct columns
2. Nested object → flattened with `_` separator
3. Array of objects field → separate child table with `_parent_id`
4. Array of primitives field → serialized TEXT column
5. Depth > 5 → TEXT + `depth_exceeded` warning
6. Circular reference → `"[Circular]"` + warning
7. Mixed string/number column → inferred as TEXT
8. SQL reserved keyword as key → renamed + warning
9. Duplicate column names → `_2` suffix
10. Empty object in array → row of nulls
11. Empty array field → empty child table created
12. Array with > 1000 items → truncated to 1000 + `array_truncated` warning
13. `null` value → NULL in SQLite row
14. Boolean value → `0` or `1`
15. Integer > MAX_SAFE_INTEGER → TEXT
16. Unicode key → normalized safe name
17. Deeply nested (3 levels) → correct table hierarchy

## Done When
- [ ] All 17 test cases pass
- [ ] `pnpm --filter @elliot/core test` exits 0
- [ ] Coverage ≥ 85% for `sqlite/` directory
