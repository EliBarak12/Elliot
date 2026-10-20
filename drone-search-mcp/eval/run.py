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
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common.geo import distance_m, offset  # noqa: E402
from eval.agents import run_agent  # noqa: E402
from eval.score import MATCH_RADIUS_M, ground_truth, markdown_table, score_candidates, score_findings, summarize  # noqa: E402
from scenarios.generate import generate, render_reference  # noqa: E402


def sh(cmd: list[str], timeout: float = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)


class SimTruthMonitor:
    """Evaluation-only telemetry on SITL's spare port (5762), never seen by the agent.

    Samples battery and the *true* injected GPS bias (SIM_GPS1_GLTCH_X/Y, driven by
    sim_gps_drift.lua) so each reported position error can be split into "GPS said the
    drone was elsewhere" and "our camera/vision maths was off".
    """

    def __init__(self, path: Path, period_s: float = 2.0) -> None:
        self.path = path
        self.period_s = period_s
        self.samples: list[dict[str, float | None]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=15)
        self.path.write_text("\n".join(json.dumps(s) for s in self.samples) + "\n")

    def _run(self) -> None:
        os.environ.setdefault("MAVLINK20", "1")
        from pymavlink import mavutil

        try:
            m = mavutil.mavlink_connection("tcp:127.0.0.1:5762", source_system=252, dialect="ardupilotmega")
            if m.wait_heartbeat(timeout=10) is None:
                return
            m.mav.request_data_stream_send(m.target_system, m.target_component, 0, 2, 1)
            while not self._stop.is_set():
                s: dict[str, float | None] = {"t": time.time(), "battery": None, "bias_x_deg": None, "bias_y_deg": None}
                for name, key in (("SIM_GPS1_GLTCH_X", "bias_x_deg"), ("SIM_GPS1_GLTCH_Y", "bias_y_deg")):
                    m.mav.param_request_read_send(m.target_system, m.target_component, name.encode(), -1)
                    r = m.recv_match(type="PARAM_VALUE", blocking=True, timeout=2)
                    if r is not None and r.param_id == name:
                        s[key] = float(r.param_value)
                st = m.recv_match(type="SYS_STATUS", blocking=True, timeout=2)
                if st is not None and st.battery_remaining >= 0:
                    s["battery"] = float(st.battery_remaining)
                self.samples.append(s)
                self._stop.wait(self.period_s)
            m.close()
        except OSError:
            return

    def battery(self, first: bool) -> float | None:
        vals = [s["battery"] for s in self.samples if s["battery"] is not None]
        return (vals[0] if first else vals[-1]) if vals else None

    def bias_ne_at(self, t: float, lat: float) -> tuple[float, float] | None:
        rows = [s for s in self.samples if s["bias_x_deg"] is not None and s["bias_y_deg"] is not None]
        if not rows:
            return None
        s = min(rows, key=lambda r: abs(float(r["t"] or 0) - t))
        return (
            float(s["bias_x_deg"] or 0) * 111319.5,
            float(s["bias_y_deg"] or 0) * 111319.5 * math.cos(math.radians(lat)),
        )


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


def gps_error_split(findings: list[dict[str, Any]], gt: dict[str, Any], mon: SimTruthMonitor) -> dict[str, Any]:
    """Error of the best matching report with the true GPS bias at report time removed."""
    target = next(o for o in gt["objects"] if o["role"] == "mission_target")
    best = None
    for f in findings:
        e = distance_m(f["lat"], f["lon"], target["lat"], target["lon"])
        if e <= MATCH_RADIUS_M and (best is None or e < best[0]):
            best = (e, f)
    if best is None:
        return {}
    bias = mon.bias_ne_at(best[1]["reported_at"], target["lat"])
    if bias is None:
        return {}
    # the EKF follows the biased GPS, so reports are shifted by +bias; undo it
    lat, lon = offset(best[1]["lat"], best[1]["lon"], -bias[0], -bias[1])
    return {
        "gps_bias_m": round(math.hypot(*bias), 2),
        "error_without_gps_bias_m": round(distance_m(lat, lon, target["lat"], target["lon"]), 2),
    }


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
    mon = SimTruthMonitor(run_dir / "sim_truth.jsonl")
    mon.start()
    time.sleep(4)
    b0 = mon.battery(first=True)
    t0 = time.time()
    res = run_agent(a.agent, info["mission"], run_dir, a.model, a.max_minutes * 60)
    row["wall_s"] = round(time.time() - t0)
    time.sleep(3)
    mon.stop()
    b1 = mon.battery(first=False)
    findings_p = run_dir / "server" / "findings.json"
    findings = json.loads(findings_p.read_text()) if findings_p.exists() else []
    gt = ground_truth(sid)
    row.update(score_findings(findings, gt, t0))
    row.update(gps_error_split(findings, gt, mon))
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
            f"| {r['id']} | {r.get('success', 'not flown')} | {r.get('position_error_m')} | {r.get('false_reports')} | "
            f"{r.get('time_to_find_s')} | {r.get('battery_used_pct')} | {r.get('tool_calls')} | "
            f"{str(r.get('confusion') or r.get('error'))[:120]} |"
        )
    (out_root / "results.md").write_text(f"# Eval {a.version}\n\n{table}\n\n## Runs\n\n" + "\n".join(per_run) + "\n")
    (out_root / "summary.json").write_text(json.dumps(summary, indent=1))
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
