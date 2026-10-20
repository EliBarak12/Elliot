"""Agent drivers for the eval harness: Claude flies the mission using only the MCP tools.

* ``api``        - Anthropic Messages API with a manual tool loop over the MCP server
                   (needs ANTHROPIC_API_KEY). Images returned by tools are passed through.
* ``claude-cli`` - headless Claude Code (``claude -p``) with the server as its only MCP
                   server and every built-in tool disabled (it cannot read files, so it
                   cannot peek at ground truth).

Both return an AgentResult with the tool-call log and the final message, whose last line
the prompt asks to be ``CONFUSION: ...`` - the agent's own note on unclear tool output.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SYSTEM_PROMPT = """\
You are the pilot-in-command of a simulated search drone, controlled only through the
drone-search MCP tools. The drone starts landed at home. Work efficiently: every tool call
and every inspection costs time and battery.

Rules:
- Verify before reporting: look at a close-up of the candidate yourself (execute_search can
  inspect the top candidates for you with inspect_top; inspect_candidate fetches more). Report
  with report_finding only when a close-up shows the target. Report the target once.
- Never report an object you are unsure about; a wrong report is worse than none.
- If a search yields no convincing candidate, you may re-plan (e.g. lower altitude, more overlap).
- When finished (target reported, or you give up), call return_home with wait=false, then stop.
- End your final message with one line starting with "CONFUSION:" naming any tool output that
  was unclear or missing information you needed, or "CONFUSION: none".
"""


def mission_prompt(mission: dict[str, Any]) -> str:
    parts = ["Mission: find the target object inside the search area and report its GPS position."]
    if mission.get("target_text"):
        parts.append(f"Target description: {mission['target_text']}.")
    if mission.get("reference_image"):
        parts.append(
            f"Reference photo of the target (pass this path to set_search_target): {mission['reference_image']}"
        )
    poly = mission["search_area"]["polygon_latlon"]
    parts.append(f"Search area polygon [lat, lon]: {json.dumps([[round(a, 7), round(b, 7)] for a, b in poly])}")
    return "\n".join(parts)


@dataclass
class AgentResult:
    final_text: str = ""
    tool_calls: list[str] = field(default_factory=list)
    turns: int = 0
    error: str | None = None
    transcript_path: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def confusion(self) -> str:
        for line in reversed(self.final_text.strip().splitlines()):
            if line.strip().upper().startswith("CONFUSION:"):
                return line.split(":", 1)[1].strip()
        return "(not stated)"


def server_command(output_dir: Path) -> list[str]:
    root = Path(__file__).resolve().parents[1]
    return [str(root / ".venv" / "bin" / "python"), "-m", "server", "--allow-actuation", "--output", str(output_dir)]


# ------------------------------------------------------------------ claude -p
def run_claude_cli(mission: dict[str, Any], out_dir: Path, model: str, timeout_s: float) -> AgentResult:
    root = Path(__file__).resolve().parents[1]
    cmd = server_command(out_dir / "server")
    cfg = {
        "mcpServers": {
            "drone-search": {
                "type": "stdio",
                "command": cmd[0],
                "args": cmd[1:],
                "env": {k: v for k, v in os.environ.items() if k.startswith("DSM_")},
            }
        }
    }
    cfg_path = out_dir / "mcp.json"
    cfg_path.write_text(json.dumps(cfg))
    transcript = out_dir / "transcript.jsonl"
    args = [
        "claude",
        "-p",
        mission_prompt(mission),
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--mcp-config",
        str(cfg_path),
        "--strict-mcp-config",
        "--tools",
        "",
        "--allowedTools",
        "mcp__drone-search__*",
        "--system-prompt",
        SYSTEM_PROMPT,
        "--max-turns",
        "40",
    ]
    res = AgentResult(transcript_path=str(transcript))
    # A fresh, standalone Claude Code: drop every CLAUDE* variable inherited from a parent
    # session (session ids, ingress tokens, messaging sockets), or the child attaches to it.
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update({"MCP_TOOL_TIMEOUT": str(int(timeout_s * 1000)), "MCP_TIMEOUT": "60000"})
    with open(transcript, "w") as fh:
        try:
            p = subprocess.run(args, stdout=fh, stderr=subprocess.PIPE, text=True, timeout=timeout_s, cwd=root, env=env)
            if p.returncode != 0:
                res.error = f"claude exited {p.returncode}: {p.stderr[-500:]}"
        except subprocess.TimeoutExpired:
            res.error = f"agent timed out after {timeout_s:.0f}s"
    for line in transcript.read_text().splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            res.turns += 1
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    res.tool_calls.append(block["name"].replace("mcp__drone-search__", ""))
                elif block.get("type") == "text":
                    res.final_text = block["text"]
        elif ev.get("type") == "result":
            usage = ev.get("usage") or {}
            res.input_tokens = int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0))
            res.output_tokens = int(usage.get("output_tokens", 0))
            if ev.get("result"):
                res.final_text = ev["result"]
    return res


# ------------------------------------------------------------------ Messages API
def run_api(mission: dict[str, Any], out_dir: Path, model: str, timeout_s: float) -> AgentResult:
    return asyncio.run(_run_api(mission, out_dir, model, timeout_s))


async def _run_api(mission: dict[str, Any], out_dir: Path, model: str, timeout_s: float) -> AgentResult:
    import anthropic
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    cmd = server_command(out_dir / "server")
    res = AgentResult(transcript_path=str(out_dir / "transcript.jsonl"))
    client = anthropic.Anthropic()
    t_end = time.time() + timeout_s
    log = open(out_dir / "transcript.jsonl", "w")  # noqa: SIM115
    try:
        transport = StdioTransport(command=cmd[0], args=cmd[1:], env=dict(os.environ))
        async with Client(transport, timeout=timeout_s) as mcp:
            tools: Any = [
                {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
                for t in await mcp.list_tools()
            ]
            messages: Any = [{"role": "user", "content": mission_prompt(mission)}]
            for _ in range(40):
                if time.time() > t_end:
                    res.error = f"agent timed out after {timeout_s:.0f}s"
                    break
                resp = client.messages.create(
                    model=model,
                    max_tokens=2048,
                    system=SYSTEM_PROMPT,
                    tools=tools,
                    messages=messages,
                )
                res.turns += 1
                res.input_tokens += resp.usage.input_tokens
                res.output_tokens += resp.usage.output_tokens
                content = [b.model_dump() for b in resp.content]
                log.write(json.dumps({"role": "assistant", "content": content}) + "\n")
                messages.append({"role": "assistant", "content": content})
                texts = [b.text for b in resp.content if b.type == "text"]
                if texts:
                    res.final_text = texts[-1]
                uses = [b for b in resp.content if b.type == "tool_use"]
                if not uses:
                    break
                results = []
                for u in uses:
                    res.tool_calls.append(u.name)
                    r = await mcp.call_tool(u.name, u.input, raise_on_error=False)
                    blocks: list[dict[str, Any]] = []
                    for c in r.content:
                        if c.type == "text":
                            blocks.append({"type": "text", "text": c.text})
                        elif c.type == "image":
                            blocks.append(
                                {
                                    "type": "image",
                                    "source": {"type": "base64", "media_type": c.mimeType, "data": c.data},
                                }
                            )
                    results.append(
                        {"type": "tool_result", "tool_use_id": u.id, "content": blocks, "is_error": bool(r.is_error)}
                    )
                    log.write(
                        json.dumps(
                            {
                                "role": "tool",
                                "name": u.name,
                                "input": u.input,
                                "text": [b.get("text") for b in blocks if b["type"] == "text"],
                            }
                        )
                        + "\n"
                    )
                messages.append({"role": "user", "content": results})
    except Exception as exc:  # recorded per run; the harness continues with the next scenario
        res.error = f"{type(exc).__name__}: {exc}"
    finally:
        log.close()
    return res


def run_agent(kind: str, mission: dict[str, Any], out_dir: Path, model: str, timeout_s: float) -> AgentResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    if kind == "api":
        return run_api(mission, out_dir, model, timeout_s)
    return run_claude_cli(mission, out_dir, model, timeout_s)
