# Task 068 — API Key Auth on All Elliot Endpoints

## Goal
Add a simple API key guard to both `elliot-mcp-plugin` (:3000) and `elliot-connector-runtime` (:3001). If `ELLIOT_API_KEY` is set, every inbound HTTP request must carry `X-Elliot-Key: <key>`. Studio reads its key from `VITE_API_KEY` and injects it automatically.

## Why
Right now both services are completely open. Anyone who can reach port 3000 or 3001 can call your tools, read your session log, and inspect your connector config. A single env var protects the whole surface.

## Backend — shared middleware

### `packages/core/src/elliot_core/auth_middleware.py`

```python
from __future__ import annotations
import os
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_BYPASS = {"/healthz", "/"}

class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        key = os.environ.get("ELLIOT_API_KEY")
        if not key or request.url.path in _BYPASS:
            return await call_next(request)
        provided = request.headers.get("X-Elliot-Key", "")
        if provided != key:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
```

Wire into both `server.py` files:
```python
from elliot_core.auth_middleware import ApiKeyMiddleware
app.add_middleware(ApiKeyMiddleware)
```

## Studio — inject key on all requests

```ts
// src/client/http.ts
const KEY = import.meta.env.VITE_API_KEY ?? "";
export const headers = KEY ? { "X-Elliot-Key": KEY } : {};
```

All `fetch` / MCP client calls pass `headers` so Studio works transparently.

## Environment variables

| Variable | Where | Notes |
|---|---|---|
| `ELLIOT_API_KEY` | plugin + runtime | Leave unset for local dev (no auth) |
| `VITE_API_KEY` | studio build | Must match `ELLIOT_API_KEY` |

## Tests

```python
def test_rejects_missing_key(monkeypatch, client):
    monkeypatch.setenv("ELLIOT_API_KEY", "secret")
    r = client.get("/v1/sessions")
    assert r.status_code == 401

def test_accepts_correct_key(monkeypatch, client):
    monkeypatch.setenv("ELLIOT_API_KEY", "secret")
    r = client.get("/v1/sessions", headers={"X-Elliot-Key": "secret"})
    assert r.status_code == 200

def test_bypasses_healthz(monkeypatch, client):
    monkeypatch.setenv("ELLIOT_API_KEY", "secret")
    r = client.get("/healthz")
    assert r.status_code == 200
```

## Estimate
3–4 hours
