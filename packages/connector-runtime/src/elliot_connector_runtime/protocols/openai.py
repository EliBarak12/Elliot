"""OpenAI-compatible /v1/chat/completions endpoint for connector tools.

Elliot has no LLM behind this endpoint — it exposes connector tools to
OpenAI-style clients. The function descriptors are advertised so a client's
model can pick a tool, and a follow-up request carrying the chosen tool (as a
``tool`` role message) executes it and returns the rows as the tool result.
"""

from __future__ import annotations

import json as _json
import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from elliot_core.errors import ElliotError
from elliot_core.types import ConnectorConfig, ToolDefinition

from ..audit import AuditLog
from ..executor import ToolExecutor


class _Message(BaseModel):
    role: str
    content: str | None = None


class ChatRequest(BaseModel):
    model: str = "elliot"
    messages: list[_Message]
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None


def build_openai_tools(config: ConnectorConfig) -> list[dict[str, Any]]:
    """Convert ConnectorConfig tools to OpenAI function-calling tool descriptors."""
    type_map = {
        "string": "string",
        "integer": "integer",
        "number": "number",
        "boolean": "boolean",
        "date": "string",
    }
    result = []
    for td in config.tools:
        props: dict[str, Any] = {}
        required: list[str] = []
        for p in td.parameters:
            schema: dict[str, Any] = {
                "type": type_map.get(p.type, "string"),
                "description": p.description,
            }
            if p.enum:
                schema["enum"] = p.enum
            props[p.name] = schema
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


def _completion(model: str, message: dict[str, Any]) -> dict[str, Any]:
    """Wrap a response message in the OpenAI chat.completion envelope."""
    now = int(time.time())
    return {
        "id": f"chatcmpl-{now}",
        "object": "chat.completion",
        "created": now,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _parse_tool_message(content: str | None) -> tuple[str, dict[str, Any]]:
    """Extract (tool_id, arguments) from a ``tool`` role message.

    Accepts either a bare tool id, or a JSON object
    ``{"tool"|"name": "<id>", "arguments": {...}}`` — the latter lets a caller
    pass arguments, which the previous implementation silently dropped.
    """
    raw = (content or "").strip()
    if raw.startswith("{"):
        try:
            obj = _json.loads(raw)
        except _json.JSONDecodeError:
            return raw, {}
        tool_id = obj.get("tool") or obj.get("name") or ""
        args = obj.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = _json.loads(args)
            except _json.JSONDecodeError:
                args = {}
        return str(tool_id), args if isinstance(args, dict) else {}
    return raw, {}


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

        # No tool selected yet: advertise the available function descriptors so
        # the client's model can choose one.
        if not last or last.role != "tool":
            message: dict[str, Any] = {"role": "assistant", "content": None, "tool_calls": []}
            resp = _completion(req.model, message)
            resp["tools"] = build_openai_tools(config)
            return resp

        tool_id, arguments = _parse_tool_message(last.content)
        td = tool_map.get(tool_id)
        if td is None:
            return _completion(
                req.model,
                {
                    "role": "tool",
                    "content": _json.dumps(
                        {"error": {"code": "TOOL_NOT_FOUND", "message": f"Unknown tool: {tool_id}"}}
                    ),
                },
            )

        t0 = time.monotonic()
        try:
            result = await executor.execute(td, arguments)
            duration = (time.monotonic() - t0) * 1000
            audit.record(td.id, arguments, len(result.rows), duration)
            content: dict[str, Any] = {"rows": result.rows, "count": len(result.rows)}
            # `result.truncated` is set when the executor capped the row set at
            # ELLIOT_MAX_RESULT_ROWS — pass the marker through.
            if result.truncated:
                content["truncated"] = True
            return _completion(req.model, {"role": "tool", "content": _json.dumps(content)})
        except Exception as exc:
            # Never let the exception escape as a bare 500 — return it as a
            # structured tool result so the OpenAI-style client can read it.
            duration = (time.monotonic() - t0) * 1000
            audit.record(td.id, arguments, 0, duration, error=str(exc))
            code = exc.code if isinstance(exc, ElliotError) else "INTERNAL_ERROR"
            msg = exc.message if isinstance(exc, ElliotError) else "Tool execution failed."
            return _completion(
                req.model,
                {
                    "role": "tool",
                    "content": _json.dumps({"error": {"code": code, "message": msg}}),
                },
            )
