"""Spawn a headless Claude Code agent that drives Elliot through the MCP plugin.

This is the literal "real user" simulation: a fresh ``claude`` subprocess
with its own MCP config pointing at our running Elliot plugin. The agent
discovers Elliot's tools the same way an end-user agent would — via
``prompts/list`` + ``tools/list`` over the streamable-HTTP transport — and
picks tools itself, with us only providing a natural-language task.

Auth: the harness ``claude`` binary picks up the OAuth file descriptor set
in this environment, so no API key is required to run from CI inside the
Anthropic environment. Outside, set ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentRun:
    """Captured result of a single headless Claude Code invocation."""

    exit_code: int
    result_text: str
    num_turns: int
    total_cost_usd: float
    duration_ms: int
    raw: dict[str, Any]

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
    allowed_tools: list[str] | None = None,
    max_budget_usd: float = 1.50,
    timeout_seconds: int = 600,
    extra_args: list[str] | None = None,
) -> AgentRun:
    """Run ``claude -p`` once against the given MCP URL and return its result.

    ``allowed_tools`` defaults to "only Elliot's MCP tools" so the agent can't
    cheat by using ``Bash``/``Edit`` to build the connector by hand — every
    write to session state must go through the plugin we're testing.
    """
    if allowed_tools is None:
        allowed_tools = ["mcp__elliot__*"]

    mcp_config = workspace / "mcp.json"
    mcp_config.write_text(json.dumps({"mcpServers": {"elliot": {"type": "http", "url": mcp_url}}}))

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
        "--output-format",
        "json",
        "--max-budget-usd",
        str(max_budget_usd),
        "--no-session-persistence",
    ]
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend(["-p", prompt])

    env = {**os.environ, "CLAUDE_CODE_SIMPLE": "0"}

    completed = subprocess.run(
        cmd,
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )

    stdout = completed.stdout.strip()
    parsed: dict[str, Any]
    try:
        parsed = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        # Some failure modes (rate-limit, network error) print plain text
        # before exiting; surface that verbatim so the test failure is
        # debuggable.
        parsed = {"is_error": True, "result": stdout, "stderr": completed.stderr}

    return AgentRun(
        exit_code=completed.returncode,
        result_text=str(parsed.get("result", "")),
        num_turns=int(parsed.get("num_turns", 0)),
        total_cost_usd=float(parsed.get("total_cost_usd", 0.0)),
        duration_ms=int(parsed.get("duration_ms", 0)),
        raw=parsed,
    )
