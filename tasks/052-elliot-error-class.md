# 052 — ElliotError Class

**Sprint**: 4 | **Estimate**: 1h | **Depends on**: 004

## Objective
Central error type used everywhere in the codebase. Must be created early but applied throughout in this sprint.

## Files to Create

### `packages/core/src/errors.ts`
```typescript
export class ElliotError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly detail?: unknown,
  ) {
    super(message);
    this.name = 'ElliotError';
  }
}

export function isElliotError(err: unknown): err is ElliotError {
  return err instanceof ElliotError;
}

export function toMcpErrorContent(err: unknown): { type: 'text'; text: string } {
  if (isElliotError(err)) {
    return { type: 'text', text: `[${err.code}] ${err.message}` };
  }
  return { type: 'text', text: `Unexpected error: ${String(err)}` };
}
```

**Error codes used across the system** (document all in this file as string constants):
`INVALID_SQL`, `MISSING_PARAM`, `INVALID_PARAM_TYPE`, `SOURCE_FETCH_FAILED`, `FILE_NOT_FOUND`, `FILE_PARSE_ERROR`, `TOOL_NOT_FOUND`, `TOOL_NAME_CONFLICT`, `INVALID_CONNECTOR`, `RATE_LIMIT_EXCEEDED`, `UNAUTHORIZED`, `SESSION_LOAD_FAILED`, `SESSION_SAVE_FAILED`

## Done When
- [ ] `ElliotError` exported from `@elliot/core`
- [ ] `toMcpErrorContent` produces correctly formatted MCP tool error responses
- [ ] All existing `throw new Error(...)` in core replaced with `throw new ElliotError(...)`
