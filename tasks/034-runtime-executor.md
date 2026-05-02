# 034 — Runtime Tool Executor

**Sprint**: 3 | **Estimate**: 2h | **Depends on**: 033

## Objective
Execute tool calls against live sources, using the TTL cache to avoid redundant fetches.

## Files to Create

### `packages/connector-runtime/src/executor.ts`

**`executeToolCall(toolName: string, params: Record<string, unknown>, ctx: RuntimeContext): Promise<ToolResult>`**

`RuntimeContext` holds: `config: ConnectorConfig`, `engine: SQLiteEngine`, `cache: SourceCache`, `secrets`

Steps:
1. Find tool in `ctx.config.tools` by name — throw `ElliotError('TOOL_NOT_FOUND')` if missing
2. For each source the tool depends on:
   - Check `cache.get(sourceId)` — if hit, skip fetch
   - If miss: fetch via `fetchEndpoint()` / `readFile()` / `queryDatabase()`, flatten, load into `engine`, store in cache
3. Execute `executeTool(tool, params, engine)`
4. Append `AuditLogEntry` via `audit.append()` (fire-and-forget)
5. Return `ToolResult`

**`executeSkillCall(skillName: string, inputs: Record<string, unknown>, ctx: RuntimeContext): Promise<SkillResult>`**
- Same cache/fetch pattern, then `executeSkill()`

## Done When
- [ ] Tool call fetches source data on first call, uses cache on second call
- [ ] Cache miss triggers fetch; cache hit skips fetch
- [ ] `TOOL_NOT_FOUND` error returned for unknown tool name
