"""Tests for the harness hook adapter's payload normalization."""

from __future__ import annotations

import json
from pathlib import Path

from elliot_core.trace.hook_adapter import (
    _assistant_texts,
    _strip_mcp_prefix,
    normalize,
)

_TRANSCRIPT = [
    {"type": "user", "message": {"content": "list the animals"}},
    {
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-7",
            "content": [
                {"type": "thinking", "thinking": "I should call the list tool."},
                {"type": "text", "text": "Listing the animals now."},
            ],
        },
    },
]


def _write_transcript(tmp_path: Path) -> str:
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in _TRANSCRIPT))
    return str(path)


def test_strip_mcp_prefix() -> None:
    assert _strip_mcp_prefix("mcp__elliot__list_animals") == "list_animals"
    assert _strip_mcp_prefix("mcp__my_runtime__get_user") == "get_user"
    assert _strip_mcp_prefix("Bash") == "Bash"


def test_assistant_texts_pulls_latest_turn() -> None:
    reasoning, final = _assistant_texts(_TRANSCRIPT)
    assert reasoning == "I should call the list tool."
    assert final == "Listing the animals now."


def test_assistant_texts_empty_transcript() -> None:
    assert _assistant_texts([]) == (None, None)


def test_normalize_claude_code_post_tool_use(tmp_path: Path) -> None:
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "sess-1",
        "tool_name": "mcp__elliot__list_animals",
        "tool_input": {"species": "dog"},
        "tool_response": '{"rows":[{"id":1}]}',
        "transcript_path": _write_transcript(tmp_path),
    }
    out = normalize("claude-code", payload)
    assert out is not None
    assert out["harness"] == "claude-code"
    assert out["session_id"] == "sess-1"
    assert out["model"] == "claude-opus-4-7"
    assert len(out["events"]) == 1
    event = out["events"][0]
    assert event["tool_id"] == "list_animals"
    assert event["arguments"] == {"species": "dog"}
    assert event["reasoning"] == "I should call the list tool."
    assert "rows" in event["result_preview"]


def test_normalize_claude_code_skips_non_mcp_tool() -> None:
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "sess-1",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    }
    # Bash/Edit/etc. are not connector calls — nothing to record.
    assert normalize("claude-code", payload) is None


def test_normalize_claude_code_user_prompt() -> None:
    out = normalize(
        "claude-code",
        {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "find at-risk users"},
    )
    assert out is not None
    assert out["user_prompt"] == "find at-risk users"


def test_normalize_claude_code_stop_extracts_final_output(tmp_path: Path) -> None:
    out = normalize(
        "claude-code",
        {
            "hook_event_name": "Stop",
            "session_id": "s",
            "transcript_path": _write_transcript(tmp_path),
        },
    )
    assert out is not None
    assert out["final_output"] == "Listing the animals now."


def test_normalize_codex_post_tool_use() -> None:
    out = normalize(
        "codex",
        {
            "hook_event_name": "PostToolUse",
            "session_id": "codex-1",
            "tool_name": "mcp__elliot__get_orders",
            "tool_input": {"customer_id": 7},
            "tool_response": "ok",
        },
    )
    assert out is not None
    assert out["harness"] == "codex"
    assert out["events"][0]["tool_id"] == "get_orders"


def test_normalize_cursor_after_mcp_execution() -> None:
    out = normalize(
        "cursor",
        {
            "hook_event_name": "afterMCPExecution",
            "conversation_id": "conv-9",
            "tool_name": "mcp__elliot__list_animals",
            "tool_input": {"limit": 5},
            "tool_output": '{"rows":[]}',
            "duration": 42.0,
        },
    )
    assert out is not None
    assert out["harness"] == "cursor"
    assert out["session_id"] == "conv-9"
    event = out["events"][0]
    assert event["tool_id"] == "list_animals"
    assert event["duration_ms"] == 42.0
    assert event["result_preview"] == '{"rows":[]}'


def test_normalize_cursor_before_submit_prompt() -> None:
    out = normalize(
        "cursor",
        {"hook_event_name": "beforeSubmitPrompt", "conversation_id": "c", "prompt": "hello"},
    )
    assert out is not None
    assert out["user_prompt"] == "hello"


def test_normalize_unknown_harness_returns_none() -> None:
    assert normalize("emacs", {"hook_event_name": "PostToolUse"}) is None


def test_normalize_explicit_event_overrides_payload() -> None:
    # The installed hook config passes --event; honour it over the payload.
    out = normalize(
        "claude-code",
        {"session_id": "s", "prompt": "do the thing"},
        event="UserPromptSubmit",
    )
    assert out is not None
    assert out["user_prompt"] == "do the thing"
