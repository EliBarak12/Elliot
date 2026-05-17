"""Normalized trace-ingest schema shared by every harness hook adapter.

A harness hook adapter (Claude Code, Codex, Cursor) translates that
harness's native hook payload into this one shape and POSTs it to
``/v1/trace/ingest``. Keeping the wire shape harness-agnostic means the
console, the metrics, and the correlation logic are written once — only
the thin per-harness adapter differs.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IngestEvent(BaseModel):
    """One tool call as seen by a harness hook."""

    tool_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_rows: int = 0
    result_token_estimate: int = 0
    duration_ms: float = 0.0
    error: str | None = None
    # A bounded preview of the tool's output, lifted from the harness payload.
    result_preview: str | None = None
    # The agent's reasoning leading into this call, when the harness exposes it.
    reasoning: str | None = None
    ts: float | None = None


class IngestPayload(BaseModel):
    """A slice of one agent run, shipped by a harness hook adapter."""

    harness: str
    harness_version: str | None = None
    session_id: str
    model: str | None = None
    # The user's prompt and the agent's final answer for this run.
    user_prompt: str | None = None
    final_output: str | None = None
    events: list[IngestEvent] = Field(default_factory=list)
