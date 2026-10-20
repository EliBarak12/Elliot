"""Render an agent run as a readable, self-contained trace page.

    python eval/trace_report.py eval/results/v5/medium-7001 [--out trace.html]

Reads the run's ``transcript.jsonl`` (headless Claude Code stream-json, or the Messages-API
log) and shows, in order: the mission prompt, every message and thinking block from the
agent, every MCP tool call with its exact arguments, and every tool response, including
the images the agent was shown. With ``--truth`` the hidden ground truth and the score are
added at the end (evaluation view).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e3e3e0;--call:#2457c5;--ok:#1f7a3f;--err:#b3261e;--code:#f2f2ef}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#151517;--card:#1e1e21;--ink:#ececee;--muted:#9a9aa0;--line:#2e2e33;--call:#7aa2ff;--ok:#5fc887;--err:#ff7b72;--code:#26262a}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px} .sub{color:var(--muted);margin-bottom:20px}
.step{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.tag{display:inline-block;font-size:12px;font-weight:600;letter-spacing:.02em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
.call .tag{color:var(--call)} .result .tag{color:var(--ok)} .error .tag{color:var(--err)}
pre{background:var(--code);border-radius:6px;padding:10px;overflow-x:auto;white-space:pre-wrap;word-break:break-word;font-size:12.5px;margin:6px 0}
.imgs{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px} .imgs img{max-width:100%;max-height:360px;border-radius:6px;border:1px solid var(--line)}
details summary{cursor:pointer;color:var(--muted);font-size:13px}
table{border-collapse:collapse;margin-top:8px;font-size:13px} td,th{border:1px solid var(--line);padding:4px 8px;text-align:left}
.n{color:var(--muted);font-size:12px;float:right}
"""


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def pretty(s: str) -> str:
    try:
        return json.dumps(json.loads(s), indent=1)
    except (ValueError, TypeError):
        return s


def events_cli(path: Path) -> list[dict[str, Any]]:
    """Normalise Claude Code stream-json into steps."""
    steps: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for line in path.read_text().splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        t = e.get("type")
        if t == "assistant":
            for b in e.get("message", {}).get("content", []):
                if b.get("type") == "text" and b.get("text", "").strip():
                    steps.append({"kind": "say", "text": b["text"]})
                elif b.get("type") == "thinking" and b.get("thinking", "").strip():
                    steps.append({"kind": "think", "text": b["thinking"]})
                elif b.get("type") == "tool_use":
                    name = b["name"].replace("mcp__drone-search__", "")
                    names[b["id"]] = name
                    steps.append({"kind": "call", "name": name, "input": b.get("input", {})})
        elif t == "user":
            for b in e.get("message", {}).get("content", []):
                if not isinstance(b, dict) or b.get("type") != "tool_result":
                    continue
                content = b.get("content")
                texts, imgs = [], []
                if isinstance(content, str):
                    texts.append(content)
                for c in content if isinstance(content, list) else []:
                    if c.get("type") == "text":
                        texts.append(c["text"])
                    elif c.get("type") == "image":
                        src = c.get("source", {})
                        imgs.append(f"data:{src.get('media_type', 'image/jpeg')};base64,{src.get('data', '')}")
                steps.append(
                    {
                        "kind": "result",
                        "name": names.get(b.get("tool_use_id", ""), "?"),
                        "text": "\n".join(texts),
                        "images": imgs,
                        "is_error": bool(b.get("is_error")),
                    }
                )
        elif t == "result":
            steps.append(
                {
                    "kind": "end",
                    "duration_s": (e.get("duration_ms") or 0) / 1000,
                    "turns": e.get("num_turns"),
                    "cost": e.get("total_cost_usd"),
                    "usage": e.get("usage"),
                }
            )
    return steps


def render(run_dir: Path, truth: bool) -> str:
    sid = run_dir.name
    mission_p = ROOT / "scenarios" / "runs" / sid / "mission.json"
    if not mission_p.exists():  # results copied from a snapshot keep their scenario next to it
        mission_p = run_dir.parents[2] / "scenarios" / "runs" / sid / "mission.json"
    mission = json.loads(mission_p.read_text()) if mission_p.exists() else {}
    from eval.agents import SYSTEM_PROMPT, mission_prompt

    steps = events_cli(run_dir / "transcript.jsonl")
    out = [
        f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>Agent trace {esc(sid)}</title><style>{CSS}</style></head><body><main>",
        f"<h1>Agent trace — {esc(sid)}</h1>",
        "<div class=sub>Claude flying the simulated drone through the drone-search MCP tools only. "
        "Every tool call is shown with its exact arguments and the full response the agent received.</div>",
    ]
    out.append(f"<div class=step><div class=tag>System prompt</div><pre>{esc(SYSTEM_PROMPT)}</pre></div>")
    if mission:
        ref = mission.get("reference_image")
        img = ""
        if ref and Path(ref).exists():
            import base64

            img = f"<div class=imgs><img src='data:image/png;base64,{base64.b64encode(Path(ref).read_bytes()).decode()}'></div>"
        out.append(
            f"<div class=step><div class=tag>Mission (user message)</div><pre>{esc(mission_prompt(mission))}</pre>"
            f"<details><summary>reference photo given to the agent</summary>{img}</details></div>"
        )
    n_calls = 0
    for s in steps:
        k = s["kind"]
        if k == "say":
            out.append(
                f"<div class=step><div class=tag>Agent</div><div>{esc(s['text']).replace(chr(10), '<br>')}</div></div>"
            )
        elif k == "think":
            out.append(
                f"<div class=step><details><summary>Agent thinking</summary><pre>{esc(s['text'])}</pre></details></div>"
            )
        elif k == "call":
            n_calls += 1
            out.append(
                f"<div class='step call'><span class=n>call {n_calls}</span><div class=tag>Tool call → {esc(s['name'])}</div>"
                f"<pre>{esc(json.dumps(s['input'], indent=1))}</pre></div>"
            )
        elif k == "result":
            cls = "error" if s["is_error"] or '"error"' in s["text"][:40] else "result"
            imgs = "".join(f"<img src='{u}'>" for u in s["images"])
            body = esc(pretty(s["text"]))
            long = len(body) > 2500
            text_html = f"<details{' open' if not long else ''}><summary>response JSON ({len(s['text'])} chars)</summary><pre>{body}</pre></details>"
            out.append(
                f"<div class='step {cls}'><div class=tag>Response ← {esc(s['name'])}</div>{text_html}"
                f"{'<div class=imgs>' + imgs + '</div>' if imgs else ''}</div>"
            )
        elif k == "end":
            u = s.get("usage") or {}
            out.append(
                f"<div class=step><div class=tag>End of run</div>{s['duration_s']:.0f} s, {s.get('turns')} turns, "
                f"{n_calls} tool calls; tokens in {u.get('input_tokens', 0) + u.get('cache_read_input_tokens', 0)}, "
                f"out {u.get('output_tokens', 0)}</div>"
            )
    if truth:
        res_p = run_dir.parent / "results.jsonl"
        row = (
            next((json.loads(line) for line in res_p.read_text().splitlines() if json.loads(line)["id"] == sid), None)
            if res_p.exists()
            else None
        )
        if row:
            keys = [
                "success",
                "position_error_m",
                "error_without_gps_bias_m",
                "gps_bias_m",
                "false_reports",
                "time_to_find_s",
                "battery_used_pct",
                "tool_calls",
                "target_kind",
                "hard_twist",
                "confusion",
            ]
            rows = "".join(f"<tr><th>{k}</th><td>{esc(str(row.get(k)))}</td></tr>" for k in keys)
            out.append(
                f"<div class=step><div class=tag>Score vs hidden ground truth (evaluation only)</div><table>{rows}</table></div>"
            )
    out.append("</main></body></html>")
    return "".join(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--no-truth", action="store_true")
    a = p.parse_args()
    out = a.out or a.run_dir / "trace.html"
    out.write_text(render(a.run_dir, not a.no_truth))
    print(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
