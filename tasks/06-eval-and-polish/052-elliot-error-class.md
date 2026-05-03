# 052 — ElliotError Class

**Sprint**: 4 | **Estimate**: 1h | **Depends on**: 004

## Objective
Central error type used everywhere in the codebase.

## Files to Create

### `packages/core/src/elliot_core/errors.py`
```python
class ElliotError(Exception):
    def __init__(self, code: str, message: str, detail: object = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

def is_elliot_error(err: object) -> bool:
    return isinstance(err, ElliotError)

def to_mcp_error_content(err: object) -> dict:
    if isinstance(err, ElliotError):
        return {"type": "text", "text": f"[{err.code}] {err.message}"}
    return {"type": "text", "text": f"Unexpected error: {err}"}
```

**Error codes** (document as constants):
`INVALID_SQL`, `MISSING_PARAM`, `INVALID_PARAM_TYPE`, `SOURCE_FETCH_FAILED`, `FILE_NOT_FOUND`, `FILE_PARSE_ERROR`, `TOOL_NOT_FOUND`, `TOOL_NAME_CONFLICT`, `INVALID_CONNECTOR`, `RATE_LIMIT_EXCEEDED`, `UNAUTHORIZED`, `SESSION_LOAD_FAILED`, `SESSION_SAVE_FAILED`

## Done When
- [ ] `ElliotError` exported from `elliot_core`
- [ ] `to_mcp_error_content` produces correctly formatted MCP tool error responses
- [ ] All existing `raise Exception(...)` in core replaced with `raise ElliotError(...)`
