# Task 036 — Runtime: OpenAI-Compatible Endpoint & Audit Log

## Goal
Add two capabilities to the connector runtime's FastAPI app:
1. `protocols/openai.py` — an `/v1/chat/completions`-style endpoint that wraps the connector's tools so any OpenAI-compatible client can call them.
2. `audit.py` — an append-only NDJSON audit log that records every tool invocation.

## Files to create

### `src/elliot_connector_runtime/audit.py`

```python
from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any


class AuditLog:
    """Append-only NDJSON audit log. Thread-safe."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def record(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        result_row_count: int,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        entry = {
            "ts": time.time(),
            "tool_id": tool_id,
            "arguments": arguments,
            "result_row_count": result_row_count,
            "duration_ms": round(duration_ms, 2),
        }
        if error:
            entry["error"] = error
        line = json.dumps(entry, separators=(",", ":")) + "\n"
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    def tail(self, n: int = 100) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        return [json.loads(l) for l in lines[-n:] if l.strip()]
```

### `src/elliot_connector_runtime/protocols/__init__.py`

```python
```

### `src/elliot_connector_runtime/protocols/openai.py`

```python
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from elliot_core.types import ConnectorConfig, ToolDefinition

from ..audit import AuditLog
from ..executor import ToolExecutor


router = APIRouter(prefix="/v1")


class _Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "elliot"
    messages: list[_Message]
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None


def build_openai_tools(config: ConnectorConfig) -> list[dict]:
    """Convert ConnectorConfig tools to OpenAI function-calling tool descriptors."""
    result = []
    for td in config.tools:
        props = {}
        required = []
        for p in td.parameters:
            type_map = {"string": "string", "integer": "integer", "number": "number", "boolean": "boolean"}
            props[p.name] = {"type": type_map.get(p.type, "string"), "description": p.description}
            if p.required:
                required.append(p.name)
        result.append({
            "type": "function",
            "function": {
                "name": td.id,
                "description": td.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        })
    return result


def register_openai_routes(
    app_router: APIRouter,
    config: ConnectorConfig,
    executor: ToolExecutor,
    audit: AuditLog,
) -> None:
    tool_map: dict[str, ToolDefinition] = {t.id: t for t in config.tools}

    @app_router.post("/chat/completions")
    async def chat_completions(req: ChatRequest) -> dict:
        last = req.messages[-1] if req.messages else None
        if not last or last.role != "tool":
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": req.model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": None, "tool_calls": []},
                    "finish_reason": "stop",
                }],
                "tools": build_openai_tools(config),
            }

        import json as _json
        tool_id = last.content
        td = tool_map.get(tool_id)
        if td is None:
            return {"error": f"Unknown tool: {tool_id}"}

        t0 = time.monotonic()
        try:
            result = await executor.execute(td, {})
            duration = (time.monotonic() - t0) * 1000
            audit.record(td.id, {}, len(result.rows), duration)
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "tool", "content": _json.dumps(result.rows)}, "finish_reason": "stop"}],
            }
        except Exception as exc:
            duration = (time.monotonic() - t0) * 1000
            audit.record(td.id, {}, 0, duration, error=str(exc))
            raise
```

## Wire into `server.py`

```python
from .audit import AuditLog
from .protocols.openai import register_openai_routes, build_openai_tools
import os

audit_path = os.environ.get("ELLIOT_AUDIT_LOG", ".elliot/audit.ndjson")
audit = AuditLog(audit_path)

openai_router = APIRouter()
register_openai_routes(openai_router, config, executor, audit)
app.include_router(openai_router)

@app.get("/v1/audit")
async def get_audit(n: int = 100) -> list:
    return audit.tail(n)
```

## Notes
- The audit log is NDJSON — one JSON object per line — so it can be streamed, grepped, and imported into any log tool.
- The `/v1/chat/completions` endpoint is intentionally minimal: full tool-calling orchestration is the job of the user's coding agent, not the runtime.
- `AuditLog` uses a threading lock so it is safe under uvicorn's default single-process + asyncio threading model.
