# 026 — Plugin HTTP Server

**Sprint**: 2 | **Estimate**: 3h | **Depends on**: 025

## Objective
FastAPI + uvicorn server exposing the MCP plugin over HTTP. All connections — Claude Code, Codex, and Studio — connect here.

## Files to Create

### `packages/mcp-plugin/src/elliot_mcp_plugin/main.py`
```python
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.server import create_elliot_server

session = ElliotSession(cwd=os.environ.get("ELLIOT_WORKSPACE", "."))
session.load()

mcp = create_elliot_server(session)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    session.save()

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_headers=["*"],
    allow_methods=["*"],
)

# Mount MCP as streamable HTTP ASGI app at /mcp
app.mount("/mcp", mcp.streamable_http_app())
```

**Run command:**
```bash
uv run uvicorn elliot_mcp_plugin.main:app --port 3000 --reload \
  --app-dir packages/mcp-plugin/src
```

## Done When
- [ ] `uvicorn elliot_mcp_plugin.main:app --port 3000` starts without error
- [ ] `curl -X POST http://localhost:3000/mcp` receives a valid MCP response
- [ ] CORS header present for `http://localhost:5173`
- [ ] Session saved on shutdown (lifespan)
