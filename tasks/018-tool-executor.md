# 018 — Tool Executor

**Sprint**: 1 | **Estimate**: 3h | **Depends on**: 017, 009

## Objective
Execute a tool definition against the SQLite engine with parameter validation, type coercion, and response shaping.

## Files to Create

### `packages/core/src/tools/executor.ts`

**`executeTool(tool: ToolDefinition, params: Record<string, unknown>, engine: SQLiteEngine): ToolResult`**

Steps:
1. Validate and coerce params against `tool.parameters`:
   - Type coercion: `"42"` → `42` for INTEGER params; `"true"` → `1`
   - Missing required param → throw `ElliotError('MISSING_PARAM', ...)`
   - Wrong type (can't coerce) → throw `ElliotError('INVALID_PARAM_TYPE', ...)`
2. Re-validate SQL via `validateToolSql()` (defense in depth)
3. Run `engine.query(tool.sql, boundParams)` — record latency
4. Apply `responseShape`:
   - `fields`: keep only listed field names
   - `rename`: rename fields per map
   - `maxRows`: slice result to limit
5. Set `truncated: true` in meta if rows were sliced
6. Return `ToolResult: { rows, meta: { rowCount, latencyMs, truncated } }`

## Done When
- [ ] Correct rows returned for SELECT with params
- [ ] `maxRows` truncation sets `truncated: true`
- [ ] `responseShape.fields` filters columns
- [ ] `"42"` coerced to `42` for INTEGER param
- [ ] Missing required param throws `ElliotError`
