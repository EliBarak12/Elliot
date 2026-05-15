"""Spawn a headless Claude Code agent that drives an MCP server through ``claude -p``.

Two roles use this helper:

* **Builder / Reviewer** point at the Elliot plugin (port 3000) and call
  ``mcp__elliot__*`` tools to design / observe a connector.
* **Consumer** points at a deployed connector runtime (port 3001) and
  calls the *built* tools the way an end-user agent would in production.

The subprocess is invoked with ``--output-format stream-json`` so we keep
the full turn-by-turn transcript; the retrospective parser then collapses
it into a Markdown report and a programmatic grade.

Auth: the harness ``claude`` binary picks up the OAuth file descriptor set
in this environment so no API key is required from CI inside Anthropic.
Outside, set ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent_retrospective import Retrospective, parse_stream_json_file


@dataclass(frozen=True)
class AgentRun:
    """Captured result of a single headless Claude Code invocation."""

    exit_code: int
    result_text: str
    num_turns: int
    total_cost_usd: float
    duration_ms: int
    raw: dict[str, Any]
    stream_log: Path
    retro: Retrospective

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.raw.get("is_error", False)


def claude_is_available() -> bool:
    return shutil.which("claude") is not None


def run_claude_agent(
    prompt: str,
    *,
    mcp_url: str,
    workspace: Path,
    role: str = "builder",
    server_name: str = "elliot",
    allowed_tool_prefix: str = "mcp__elliot__",
    extra_allowed_tools: tuple[str, ...] = (),
    disallowed_tools: tuple[str, ...] = (
        "Bash",
        "Edit",
        "Write",
        "MultiEdit",
        "Read",
        "Grep",
        "Glob",
        "WebFetch",
        "WebSearch",
    ),
    max_budget_usd: float = 1.50,
    timeout_seconds: int = 900,
) -> AgentRun:
    """Run ``claude -p`` once against the given MCP URL and return its result.

    ``allowed_tool_prefix`` defaults to ``mcp__elliot__*`` so the agent can't
    cheat with Bash/Edit. Pass ``server_name="ecommerce"`` (or whatever the
    runtime exposes itself as) when the consumer connects to a runtime —
    the corresponding allowed-tools prefix becomes ``mcp__<name>__``.
    """
    if not server_name:
        raise ValueError("server_name must be set")

    if allowed_tool_prefix == "mcp__elliot__" and server_name != "elliot":
        allowed_tool_prefix = f"mcp__{server_name}__"

    role_dir = workspace / "agent-runs" / role
    role_dir.mkdir(parents=True, exist_ok=True)
    mcp_config = role_dir / "mcp.json"
    mcp_config.write_text(
        json.dumps({"mcpServers": {server_name: {"type": "http", "url": mcp_url}}})
    )

    stream_log = role_dir / "stream.jsonl"
    allowed_tools = [f"{allowed_tool_prefix}*", *extra_allowed_tools]

    cmd = [
        "claude",
        "--mcp-config",
        str(mcp_config),
        "--add-dir",
        str(workspace),
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        ",".join(allowed_tools),
        "--disallowedTools",
        ",".join(disallowed_tools),
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--max-budget-usd",
        str(max_budget_usd),
        "--no-session-persistence",
        "-p",
        prompt,
    ]

    env = {**os.environ, "CLAUDE_CODE_SIMPLE": "0"}

    t0 = time.time()
    with stream_log.open("wb") as fh:
        completed = subprocess.run(
            cmd,
            cwd=workspace,
            env=env,
            stdout=fh,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    elapsed_ms = int((time.time() - t0) * 1000)

    retro = parse_stream_json_file(stream_log)
    raw = retro.raw_result or {
        "is_error": True,
        "result": completed.stderr.decode(errors="replace")[:1000],
    }

    return AgentRun(
        exit_code=completed.returncode,
        result_text=retro.final_text,
        num_turns=retro.num_turns,
        total_cost_usd=retro.total_cost_usd or 0.0,
        duration_ms=retro.duration_ms or elapsed_ms,
        raw=raw,
        stream_log=stream_log,
        retro=retro,
    )
