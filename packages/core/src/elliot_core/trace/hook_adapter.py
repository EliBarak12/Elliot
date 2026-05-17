"""Harness hook adapter: normalize a coding-agent hook payload and ship it.

``elliot trace install`` wires this module into a harness's hook config. The
harness then runs it on each hook event, passing that harness's native JSON on
stdin. The adapter translates it into Elliot's normalized trace schema (see
``trace_ingest.IngestPayload``) and POSTs it to the connector runtime so the
Agent Console can show the agent's reasoning, the user's prompt and the
agent's final answer.

A hook blocks the agent until it returns, and a non-zero exit can interrupt
the agent — so every failure here is swallowed and the process always exits 0.

Run as: ``python -m elliot_core.trace.hook_adapter --harness {claude-code|codex|cursor}``
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_RUNTIME_URL = "http://localhost:3001"
_HTTP_TIMEOUT = 3.0
_PREVIEW_MAX_CHARS = 800


def _strip_mcp_prefix(tool_name: str) -> str:
    """Reduce a namespaced MCP tool name to the bare connector tool id.

    ``mcp__elliot__list_animals`` -> ``list_animals``.
    """
    if tool_name.startswith("mcp__") and "__" in tool_name[len("mcp__") :]:
        return tool_name.split("__")[-1]
    return tool_name


def _preview(value: Any) -> str | None:
    """A short, bounded string preview of a tool result."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if not text:
        return None
    return text[:_PREVIEW_MAX_CHARS] + "…" if len(text) > _PREVIEW_MAX_CHARS else text


def _read_transcript(path: Any) -> list[dict[str, Any]]:
    """Parse a JSONL transcript file into a list of entries (best effort)."""
    if not isinstance(path, str) or not os.path.isfile(path):
        return []
    out: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    out.append(entry)
    except OSError:
        return []
    return out


def _assistant_texts(transcript: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Return ``(reasoning, final_text)`` from the most recent assistant turn.

    ``reasoning`` is the concatenated ``thinking`` blocks; ``final_text`` is the
    concatenated ``text`` blocks of that turn.
    """
    for entry in reversed(transcript):
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        msg: dict[str, Any] = message if isinstance(message, dict) else entry
        content = msg.get("content")
        thinking: list[str] = []
        text: list[str] = []
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "thinking":
                    thinking.append(str(block.get("thinking", "")))
                elif block.get("type") == "text":
                    text.append(str(block.get("text", "")))
        elif isinstance(content, str):
            text.append(content)
        return (
            "\n".join(p for p in thinking if p) or None,
            "\n".join(p for p in text if p) or None,
        )
    return None, None


def _transcript_model(transcript: list[dict[str, Any]]) -> str | None:
    """Pull the model id from a transcript, if any entry records it."""
    for entry in transcript:
        message = entry.get("message")
        if isinstance(message, dict) and message.get("model"):
            return str(message["model"])
    return None


def _normalize_claude_like(
    harness: str, payload: dict[str, Any], event: str
) -> dict[str, Any] | None:
    """Normalize a Claude Code / Codex hook payload (they share a shape)."""
    session_id = str(payload.get("session_id") or "unknown")
    out: dict[str, Any] = {"harness": harness, "session_id": session_id, "events": []}
    transcript = _read_transcript(payload.get("transcript_path"))
    model = _transcript_model(transcript)
    if model:
        out["model"] = model

    event = event.lower()
    if event in ("posttooluse", "posttoolusefailure"):
        tool_name = str(payload.get("tool_name") or "")
        # Only connector/MCP tool calls matter — skip Bash/Edit/etc.
        if not tool_name.startswith("mcp__"):
            return None
        reasoning, _ = _assistant_texts(transcript)
        out["events"] = [
            {
                "tool_id": _strip_mcp_prefix(tool_name),
                "arguments": payload.get("tool_input") or {},
                "result_preview": _preview(
                    payload.get("tool_response")
                    if payload.get("tool_response") is not None
                    else payload.get("tool_output")
                ),
                "error": payload.get("error"),
                "reasoning": reasoning,
            }
        ]
        return out
    if event == "userpromptsubmit":
        out["user_prompt"] = payload.get("prompt") or payload.get("user_prompt")
        return out
    if event in ("stop", "sessionend"):
        _, final = _assistant_texts(transcript)
        out["final_output"] = final or payload.get("model_response")
        return out
    return None


def _normalize_cursor(payload: dict[str, Any], event: str) -> dict[str, Any] | None:
    """Normalize a Cursor hook payload."""
    session_id = str(payload.get("conversation_id") or payload.get("session_id") or "unknown")
    out: dict[str, Any] = {"harness": "cursor", "session_id": session_id, "events": []}

    event = event.lower()
    if event == "aftermcpexecution":
        out["events"] = [
            {
                "tool_id": _strip_mcp_prefix(str(payload.get("tool_name") or "")),
                "arguments": payload.get("tool_input") or payload.get("input") or {},
                "result_preview": _preview(payload.get("tool_output")),
                "duration_ms": float(payload.get("duration") or 0.0),
            }
        ]
        return out
    if event == "beforesubmitprompt":
        out["user_prompt"] = payload.get("prompt") or payload.get("text")
        return out
    return None


def normalize(
    harness: str, payload: dict[str, Any], event: str | None = None
) -> dict[str, Any] | None:
    """Translate one harness hook payload into an IngestPayload-shaped dict.

    Returns ``None`` when the event carries nothing worth recording.
    """
    event = event or str(payload.get("hook_event_name") or payload.get("event") or "")
    if harness in ("claude-code", "codex"):
        return _normalize_claude_like(harness, payload, event)
    if harness == "cursor":
        return _normalize_cursor(payload, event)
    return None


def _post(payload: dict[str, Any]) -> None:
    """POST a normalized trace to the connector runtime — failures are silent."""
    runtime = os.environ.get("ELLIOT_RUNTIME_URL", DEFAULT_RUNTIME_URL).rstrip("/")
    request = urllib.request.Request(
        f"{runtime}/v1/trace/ingest",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    key = os.environ.get("ELLIOT_API_KEY")
    if key:
        request.add_header("X-Elliot-Key", key)
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT):
            pass
    except (urllib.error.URLError, OSError, ValueError):
        pass


def _arg(argv: list[str], name: str) -> str | None:
    """Read ``--name value`` from argv."""
    if name in argv:
        idx = argv.index(name)
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    harness = _arg(argv, "--harness") or ""
    event = _arg(argv, "--event")

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0

    try:
        normalized = normalize(harness, payload, event)
    except Exception:
        return 0
    if normalized:
        _post(normalized)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
