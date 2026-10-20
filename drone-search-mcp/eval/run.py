"""Automated evaluation: N random scenarios, flown headless by Claude through the MCP tools.

    python eval/run.py --n 20 --version v1 [--tiers easy,medium,hard] [--seed0 1000]
                       [--agent claude-cli|api] [--model claude-sonnet-5-5] [--video]

For each run: generate a fresh random scenario (never reused for tuning), bring the
simulator up, let the agent fly the mission, then score its reports against the hidden
ground truth. Writes eval/results/<version>/{results.jsonl, results.md, <scenario>/...}.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.agents import run_agent  # noqa: E402
from eval.score import ground_truth, markdown_table, score_candidates, score_findings, summarize  # noqa: E402
from scenarios.generate import generate, render_reference  # noqa: E402


def sh(cmd: list[str], timeout: float = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)


def battery_now() -> float | None:
    """Read battery from the spare MAVLink port (5762) without touching the agent's link."""
    os.environ.setdefault("MAVLINK20", "1")
    from pymavlink import mavutil

    try:
        m = mavutil.mavlink_connection("tcp:127.0.0.1:5762", source_system=252, dialect="ardupilotmega")
        if m.wait_heartbeat(timeout=10) is None:
            return None
        m.mav.request_data_stream_send(m.target_system, m.target_component, 0, 4, 1)
        msg = m.recv_match(type="SYS_STATUS", blocking=True, timeout=10)
        m.close()
        return float(msg.battery_remaining) if msg else None
    except OSError:
        return None


def run_one(i: int, tier: str, seed: int, a: argparse.Namespace, out_root: Path) -> dict[str, Any]:
    info = generate(tier, seed, mode=a.mode)
    sid = info["id"]
    run_dir = out_root / sid
    run_dir.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {"i": i, "id": sid, "tier": tier, "seed": seed, "version": a.version}
    if a.mode != "text" and not render_reference(info):
        row["error"] = "reference render failed"
        return row
    up = sh([str(ROOT / "scripts" / "sim_up.sh"), "--scenario", str(Path(info["run_dir"]) / "scenario.json")])
    if up.returncode != 0:
        row["error"] = f"sim_up failed: {up.stdout[-300:]} {up.stderr[-300:]}"
        return row
    time.sleep(3)
    b0 = battery_now()
    t0 = time.time()
    res = run_agent(a.agent, info["mission"], run_dir, a.model, a.max_minutes * 60)
    row["wall_s"] = round(time.time() - t0)
    b1 = battery_now()
    findings_p = run_dir / "server" / "findings.json"
    findings = json.loads(findings_p.read_text()) if findings_p.exists() else []
    gt = ground_truth(sid)
    row.update(score_findings(findings, gt, t0))
    cands_p = run_dir / "server" / "candidates.json"
    if cands_p.exists():
        row.update(score_candidates(json.loads(cands_p.read_text()), gt))
    row.update(
        {
            "battery_used_pct": None if b0 is None or b1 is None else round(b0 - b1, 1),
            "tool_calls": len(res.tool_calls),
            "tool_sequence": res.tool_calls,
            "turns": res.turns,
            "confusion": res.confusion,
            "error": res.error,
            "hard_twist": gt.get("hard_twist"),
            "target_kind": gt["mission_target_kind"],
            "input_tokens": res.input_tokens,
            "output_tokens": res.output_tokens,
        }
    )
    if a.video:
        sh(
            [
                str(ROOT / ".venv" / "bin" / "python"),
                str(ROOT / "scripts" / "make_video.py"),
                str(run_dir / "server"),
                "--out",
                str(run_dir / "flight.mp4"),
                "--truth",
                str(
                    Path(os.environ.get("DSM_EVAL_DIR", Path.home() / ".drone_search_eval")) / sid / "ground_truth.json"
                ),
            ],
            timeout=600,
        )
    return row


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--version", required=True)
    p.add_argument("--tiers", default="easy,medium,hard")
    p.add_argument("--seed0", type=int, default=1000)
    p.add_argument(
        "--agent", choices=["claude-cli", "api"], default="api" if os.environ.get("ANTHROPIC_API_KEY") else "claude-cli"
    )
    p.add_argument("--model", default=os.environ.get("DSM_AGENT_MODEL", "claude-sonnet-5-5"))
    p.add_argument("--mode", choices=["image", "text", "both"], default="both")
    p.add_argument("--max-minutes", type=float, default=25)
    p.add_argument("--video", action="store_true")
    a = p.parse_args()
    tiers = a.tiers.split(",")
    out_root = ROOT / "eval" / "results" / a.version
    out_root.mkdir(parents=True, exist_ok=True)
    results = out_root / "results.jsonl"
    done = {json.loads(line)["id"] for line in results.read_text().splitlines()} if results.exists() else set()
    for i in range(a.n):
        tier, seed = tiers[i % len(tiers)], a.seed0 + i
        if f"{tier}-{seed:04d}" in done:
            continue
        print(f"[eval] run {i + 1}/{a.n}: {tier} seed {seed}", flush=True)
        try:
            row = run_one(i, tier, seed, a, out_root)
        except Exception as exc:  # keep going; the row records what broke
            row = {
                "i": i,
                "id": f"{tier}-{seed:04d}",
                "tier": tier,
                "seed": seed,
                "version": a.version,
                "error": f"{type(exc).__name__}: {exc}",
                "success": False,
                "found": False,
                "false_reports": 0,
            }
        finally:
            sh([str(ROOT / "scripts" / "sim_down.sh")])
        with open(results, "a") as fh:
            fh.write(json.dumps(row) + "\n")
        print(
            f"[eval]   success={row.get('success')} err={row.get('position_error_m')} "
            f"fp={row.get('false_reports')} calls={row.get('tool_calls')} error={row.get('error')}",
            flush=True,
        )
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    summary = summarize(rows)
    table = markdown_table(summary)
    per_run = [
        "| id | success | error_m | false_reports | time_s | battery% | calls | confusion |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        per_run.append(
            f"| {r['id']} | {r.get('success')} | {r.get('position_error_m')} | {r.get('false_reports')} | "
            f"{r.get('time_to_find_s')} | {r.get('battery_used_pct')} | {r.get('tool_calls')} | "
            f"{str(r.get('confusion') or r.get('error'))[:120]} |"
        )
    (out_root / "results.md").write_text(f"# Eval {a.version}\n\n{table}\n\n## Runs\n\n" + "\n".join(per_run) + "\n")
    (out_root / "summary.json").write_text(json.dumps(summary, indent=1))
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
