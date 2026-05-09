"""OpenAI-compatible /v1/chat/completions endpoint for connector tools."""

from __future__ import annotations

import json as _json
import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from elliot_core.types import ConnectorConfig, ToolDefinition

from ..audit import AuditLog
from ..executor import ToolExecutor


class _Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "elliot"
    messages: list[_Message]
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None


def build_openai_tools(config: ConnectorConfig) -> list[dict[str, Any]]:
    """Convert ConnectorConfig tools to OpenAI function-calling tool descriptors."""
    result = []
    for td in config.tools:
        props: dict[str, Any] = {}
        required: list[str] = []
        for p in td.parameters:
            type_map = {
                "string": "string",
                "integer": "integer",
                "number": "number",
                "boolean": "boolean",
                "date": "string",
            }
            props[p.name] = {
                "type": type_map.get(p.type, "string"),
                "description": p.description,
            }
            if p.required:
                required.append(p.name)
        result.append(
            {
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
            }
        )
    return result


def register_openai_routes(
    app_router: APIRouter,
    config: ConnectorConfig,
    executor: ToolExecutor,
    audit: AuditLog,
) -> None:
    tool_map: dict[str, ToolDefinition] = {t.id: t for t in config.tools}

    @app_router.post("/chat/completions")
    async def chat_completions(req: ChatRequest) -> dict[str, Any]:
        last = req.messages[-1] if req.messages else None
        if not last or last.role != "tool":
            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": req.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [],
                        },
                        "finish_reason": "stop",
                    }
                ],
                "tools": build_openai_tools(config),
            }

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
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "tool",
                            "content": _json.dumps(result.rows),
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        except Exception as exc:
            duration = (time.monotonic() - t0) * 1000
            audit.record(td.id, {}, 0, duration, error=str(exc))
            raise
