"""Parse a stream-json transcript from ``claude -p`` into a usable retrospective.

The CLI streams one JSON object per line when invoked with
``--output-format stream-json``. Each line is a system/assistant/user/result
event. This module collapses those into a per-turn breakdown so a test
can assert on agent behaviour, count tool calls, measure stage timing,
and dump a Markdown report a human can review.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Tools relevant to the canonical Elliot workflow. Anything else the agent
# calls (Bash, Edit, etc.) is flagged as off-policy in the retrospective.
WORKFLOW_STAGES: dict[str, tuple[str, ...]] = {
    "discover": ("elliot_upload_file", "elliot_discover_source", "elliot_refresh_source"),
    "explore": (
        "elliot_list_sources",
        "elliot_sample_data",
        "elliot_preview_source",
        "elliot_profile_source",
        "elliot_get_schema",
        "elliot_list_tables",
        "elliot_query_sql",
        "elliot_validate_sql",
        "elliot_explain_query",
    ),
    "build": (
        "elliot_create_tool",
        "elliot_update_tool",
        "elliot_preview_tool",
        "elliot_validate_tool",
        "elliot_create_skill",
        "elliot_preview_skill",
        "elliot_build_connector",
    ),
    "lint": ("elliot_lint_connector", "elliot_quality_scan"),
    "eval": ("elliot_run_eval",),
    "deploy": (
        "elliot_export_connector",
        "elliot_save_session",
        "elliot_start_runtime",
        "elliot_stop_runtime",
        "elliot_runtime_logs",
        "elliot_get_connection_config",
    ),
}

# Reverse: tool name -> stage
TOOL_TO_STAGE: dict[str, str] = {
    tool: stage for stage, tools in WORKFLOW_STAGES.items() for tool in tools
}


@dataclass
class ToolCallRecord:
    """One ``tool_use`` / ``tool_result`` pair captured from the stream."""

    name: str
    stage: str
    input_summary: str  # truncated args repr
    is_error: bool
    error_message: str | None
    output_summary: str  # truncated result repr


@dataclass
class TurnRecord:
    """A single assistant turn plus any tool results that followed it."""

    index: int
    text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


@dataclass
class Retrospective:
    exit_code: int
    succeeded: bool
    total_cost_usd: float
    duration_ms: int
    num_turns: int
    turns: list[TurnRecord] = field(default_factory=list)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    stage_counts: dict[str, int] = field(default_factory=dict)
    off_policy_tools: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    final_text: str = ""
    raw_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_TOOL_NS = re.compile(r"^mcp__elliot__(.+)$")

# Claude Code's deferred-tool loader. Counts as "tool use" but is part of
# the CLI's schema-resolution path, not an attempt to escape the policy.
_SYSTEM_TOOLS = frozenset({"ToolSearch"})


def _normalize_tool_name(name: str) -> str:
    """Strip ``mcp__elliot__`` prefix so we can compare against bare names."""
    m = _TOOL_NS.match(name)
    return m.group(1) if m else name


def _truncate(obj: Any, limit: int = 240) -> str:
    try:
        s = json.dumps(obj, default=str)
    except Exception:
        s = str(obj)
    if len(s) > limit:
        return s[:limit] + f"… [+{len(s) - limit} chars]"
    return s


def parse_stream(events: Iterable[dict[str, Any]]) -> Retrospective:
    """Collapse a sequence of stream-json events into a :class:`Retrospective`."""
    turn_records: list[TurnRecord] = []
    tool_use_index: dict[str, ToolCallRecord] = {}
    counts: Counter[str] = Counter()
    stages: Counter[str] = Counter()
    off_policy: Counter[str] = Counter()
    errors: list[str] = []
    final_text = ""
    result_event: dict[str, Any] | None = None

    for evt in events:
        evt_type = evt.get("type")

        if evt_type == "assistant":
            msg = evt.get("message", {})
            content = msg.get("content", [])
            text_parts: list[str] = []
            tool_calls_this_turn: list[ToolCallRecord] = []
            for block in content:
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    raw_name = block.get("name", "")
                    name = _normalize_tool_name(raw_name)
                    stage = TOOL_TO_STAGE.get(name, "other")
                    rec = ToolCallRecord(
                        name=name,
                        stage=stage,
                        input_summary=_truncate(block.get("input", {})),
                        is_error=False,
                        error_message=None,
                        output_summary="",
                    )
                    tool_use_index[block.get("id", "")] = rec
                    tool_calls_this_turn.append(rec)
                    counts[name] += 1
                    if raw_name.startswith("mcp__"):
                        # MCP tool — counts toward stage coverage when it's
                        # one of Elliot's, and is on-policy for any
                        # ``mcp__<server>__*`` allowed prefix the agent was
                        # given (builder = elliot, consumer = ecommerce).
                        if raw_name.startswith("mcp__elliot__"):
                            stages[stage] += 1
                    elif raw_name in _SYSTEM_TOOLS:
                        # Claude Code's internal tool-schema loader. Tracked
                        # for accounting but not treated as an escape.
                        pass
                    else:
                        off_policy[raw_name] += 1
            turn_records.append(
                TurnRecord(
                    index=len(turn_records),
                    text="\n".join(t.strip() for t in text_parts if t.strip()),
                    tool_calls=tool_calls_this_turn,
                )
            )

        elif evt_type == "user":
            # Tool results come back as user-role messages.
            msg = evt.get("message", {})
            for block in msg.get("content", []) if isinstance(msg, dict) else []:
                if block.get("type") != "tool_result":
                    continue
                use_id = block.get("tool_use_id", "")
                rec = tool_use_index.get(use_id)
                if rec is None:
                    continue
                rec.is_error = bool(block.get("is_error", False))
                payload = block.get("content")
                if isinstance(payload, list) and payload:
                    text = payload[0].get("text", "") if isinstance(payload[0], dict) else ""
                else:
                    text = str(payload or "")
                rec.output_summary = _truncate(text, limit=400)
                if rec.is_error:
                    rec.error_message = text[:240]
                    errors.append(f"{rec.name}: {text[:200]}")

        elif evt_type == "result":
            result_event = evt
            final_text = str(evt.get("result", ""))

    exit_code = 0 if (result_event and not result_event.get("is_error")) else 1
    return Retrospective(
        exit_code=exit_code,
        succeeded=exit_code == 0,
        total_cost_usd=float((result_event or {}).get("total_cost_usd", 0.0)),
        duration_ms=int((result_event or {}).get("duration_ms", 0)),
        num_turns=int((result_event or {}).get("num_turns", len(turn_records))),
        turns=turn_records,
        tool_call_counts=dict(counts),
        stage_counts=dict(stages),
        off_policy_tools=dict(off_policy),
        errors=errors,
        final_text=final_text,
        raw_result=result_event,
    )


def parse_stream_json_file(path: Path) -> Retrospective:
    """Load a stream-json file written by ``claude -p --output-format stream-json``."""
    events: list[dict[str, Any]] = []
    with path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # Stream might include an unparseable line at the head if
                # the CLI wrote a warning before the JSON envelope started.
                continue
    return parse_stream(events)


def to_markdown(retro: Retrospective, *, title: str) -> str:
    """Render a retrospective as a Markdown report a human can read end-to-end."""
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## Summary")
    lines.append(
        f"- **Outcome:** {'SUCCEEDED' if retro.succeeded else 'FAILED'} (exit {retro.exit_code})"
    )
    lines.append(f"- **Turns:** {retro.num_turns}")
    lines.append(f"- **Duration:** {retro.duration_ms / 1000:.1f}s")
    lines.append(f"- **Cost:** ${retro.total_cost_usd:.4f}")
    lines.append(
        f"- **Tool calls:** {sum(retro.tool_call_counts.values())} "
        f"({sum(retro.stage_counts.values())} on-policy, "
        f"{sum(retro.off_policy_tools.values())} off-policy)"
    )
    lines.append(f"- **Errors:** {len(retro.errors)}")
    lines.append("")

    lines.append("## Stage coverage")
    lines.append("| Stage | Tool calls |")
    lines.append("|---|---|")
    for stage in ("discover", "explore", "build", "lint", "eval", "deploy"):
        lines.append(f"| {stage} | {retro.stage_counts.get(stage, 0)} |")
    if retro.off_policy_tools:
        lines.append("")
        lines.append("**Off-policy tool calls** (agent reached outside `mcp__elliot__*`):")
        for tool, n in sorted(retro.off_policy_tools.items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{tool}` × {n}")
    lines.append("")

    lines.append("## Tool call frequency")
    lines.append("| Tool | Calls |")
    lines.append("|---|---|")
    for tool, n in sorted(retro.tool_call_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{tool}` | {n} |")
    lines.append("")

    if retro.errors:
        lines.append("## Errors encountered")
        for i, err in enumerate(retro.errors, 1):
            lines.append(f"{i}. `{err}`")
        lines.append("")

    lines.append("## Per-turn timeline")
    for turn in retro.turns:
        if not turn.text and not turn.tool_calls:
            continue
        lines.append(f"### Turn {turn.index}")
        if turn.text:
            for tl in turn.text.splitlines():
                lines.append(f"> {tl}")
        for call in turn.tool_calls:
            badge = "ERR" if call.is_error else "ok"
            lines.append(f"- **[{badge}]** `{call.name}` ({call.stage})")
            lines.append(f"    - args: `{call.input_summary}`")
            if call.is_error:
                lines.append(f"    - error: `{call.error_message}`")
            elif call.output_summary:
                lines.append(f"    - result: `{call.output_summary}`")
        lines.append("")

    if retro.final_text:
        lines.append("## Final agent reply")
        for line in retro.final_text.splitlines():
            lines.append(f"> {line}")
        lines.append("")

    return "\n".join(lines)


def grade(retro: Retrospective) -> dict[str, Any]:
    """Heuristic verdict on whether the agent did the workflow well.

    Used by the reviewer layer to flag obvious failures: missing stages,
    off-policy tool calls, retry loops on the same tool.
    """
    grades: dict[str, Any] = {}
    grades["stage_coverage"] = {
        stage: (retro.stage_counts.get(stage, 0) > 0)
        for stage in ("discover", "build", "lint", "deploy")
    }
    grades["stayed_on_policy"] = sum(retro.off_policy_tools.values()) == 0
    grades["completed_under_budget"] = retro.succeeded

    # Detect retry loops: same tool called >5 times often = thrashing
    thrashy = {name: n for name, n in retro.tool_call_counts.items() if n > 5}
    grades["potential_thrash"] = thrashy

    grades["error_count"] = len(retro.errors)
    return grades


__all__ = [
    "Retrospective",
    "TurnRecord",
    "ToolCallRecord",
    "parse_stream",
    "parse_stream_json_file",
    "to_markdown",
    "grade",
    "WORKFLOW_STAGES",
]


# Silence unused-import warnings.
_ = defaultdict  # noqa: PLW0603
