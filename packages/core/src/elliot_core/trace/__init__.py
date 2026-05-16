"""Harness hook adapters — capture an agent's run locally and ship it to Elliot.

MCP traffic shows *what* tools an agent called, but not *why*. A harness hook
runs inside the agent (Claude Code, Codex, Cursor) and can see the user's
prompt, the agent's reasoning and its final answer. This package normalizes
each harness's hook payload into one shape and ships it to the connector
runtime's ``/v1/trace/ingest`` endpoint.
"""

from __future__ import annotations

SUPPORTED_HARNESSES = ("claude-code", "codex", "cursor")
