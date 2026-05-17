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

# Hard caps on the wire payload — a harness hook adapter is untrusted input,
# so an unbounded events list or multi-megabyte text field could exhaust the
# runtime's memory. These limits are generous for any legitimate agent run.
_MAX_EVENTS = 1000
_MAX_TEXT = 20_000
_MAX_ID = 512


class IngestEvent(BaseModel):
    """One tool call as seen by a harness hook."""

    tool_id: str = Field(..., max_length=_MAX_ID)
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_rows: int = 0
    result_token_estimate: int = 0
    duration_ms: float = 0.0
    error: str | None = Field(default=None, max_length=_MAX_TEXT)
    # A bounded preview of the tool's output, lifted from the harness payload.
    result_preview: str | None = Field(default=None, max_length=_MAX_TEXT)
    # The agent's reasoning leading into this call, when the harness exposes it.
    reasoning: str | None = Field(default=None, max_length=_MAX_TEXT)
    ts: float | None = None


class IngestPayload(BaseModel):
    """A slice of one agent run, shipped by a harness hook adapter."""

    harness: str = Field(..., max_length=_MAX_ID)
    harness_version: str | None = Field(default=None, max_length=_MAX_ID)
    session_id: str = Field(..., max_length=_MAX_ID)
    model: str | None = Field(default=None, max_length=_MAX_ID)
    # The user's prompt and the agent's final answer for this run.
    user_prompt: str | None = Field(default=None, max_length=_MAX_TEXT)
    final_output: str | None = Field(default=None, max_length=_MAX_TEXT)
    events: list[IngestEvent] = Field(default_factory=list, max_length=_MAX_EVENTS)
