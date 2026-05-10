# Task 074 — Rate Limiting on Tool Execution

## Goal
Add per-IP (or per-session) rate limiting to the MCP tool execution endpoints on both services. A runaway agent or a misconfigured client cannot hammer the runtime — and through it, the user's actual upstream API.

## Library
`slowapi` — built on top of `limits`, integrates natively with FastAPI/Starlette. One new dependency, no infrastructure needed.

```toml
# add to both service pyproject.toml
"slowapi>=0.1.9"
```

## Implementation

### `packages/core/src/elliot_core/rate_limit.py`

```python
from __future__ import annotations
import os
from slowapi import Limiter
from slowapi.util import get_remote_address

def build_limiter() -> Limiter:
    return Limiter(
        key_func=get_remote_address,
        default_limits=[os.environ.get("ELLIOT_RATE_LIMIT", "120/minute")],
    )
```

### Wire into both `server.py`

```python
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from elliot_core.rate_limit import build_limiter

limiter = build_limiter()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

### Apply to the MCP tool call handler

```python
from slowapi import Limiter
from fastapi import Request

@app.post("/mcp")
@limiter.limit("120/minute")
async def mcp_handler(request: Request):
    ...
```

## Environment variables

| Variable | Default | Example |
|---|---|---|
| `ELLIOT_RATE_LIMIT` | `120/minute` | `30/minute`, `500/hour` |

## Response on limit exceeded

```json
HTTP 429 Too Many Requests
Retry-After: 43

{ "error": "rate limit exceeded", "retry_after_seconds": 43 }
```

## Tests

```python
def test_rate_limit_exceeded(monkeypatch, client):
    monkeypatch.setenv("ELLIOT_RATE_LIMIT", "2/minute")
    for _ in range(2):
        r = client.post("/mcp", json={})
    r = client.post("/mcp", json={})
    assert r.status_code == 429
    assert "retry_after" in r.json()
```

## Estimate
3–4 hours
