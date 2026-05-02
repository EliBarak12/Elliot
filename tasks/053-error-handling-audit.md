# 053 — Error Handling Audit

**Sprint**: 4 | **Estimate**: 2h | **Depends on**: 052

## Objective
Ensure every error path in the system surfaces a clean, user-readable message. No raw stack traces to agents.

## What to Do

### Plugin MCP tool handlers
Every tool handler must have a top-level try/catch:
```typescript
try {
  // ... tool logic
} catch (err) {
  return { content: [toMcpErrorContent(err)], isError: true };
}
```
Verify this pattern exists in: `source-tools.ts`, `sql-tools.ts`, `tool-tools.ts`, `skill-tools.ts`, `context-tools.ts`, `connector-tools.ts`, `studio-tools.ts`.

### Runtime executor
- `executeToolCall` wraps all errors as `ElliotError` before re-throwing
- SQLite `SQLITE_ERROR` extracts and includes the column/table name in the message

### Core library
- No raw `Error.message` leaks from `better-sqlite3` — wrap with `ElliotError('INVALID_SQL', db_err.message)`
- All `catch (err)` blocks use `isElliotError(err)` to decide whether to wrap or re-throw

## Done When
- [ ] Every MCP tool handler has try/catch returning `toMcpErrorContent`
- [ ] No `Error` thrown directly from tool handlers (only `ElliotError`)
- [ ] A bad SQL query returns a readable message, not a raw `better-sqlite3` error
