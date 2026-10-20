"""Score a mission against ground truth (evaluation only - the server never sees this)."""

from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common.geo import distance_m  # noqa: E402

MATCH_RADIUS_M = 10.0  # a report this close to the target is "the target, found"
SUCCESS_ERROR_M = 5.0  # ...and counts as a success when it is also within this


def ground_truth(sid: str) -> dict[str, Any]:
    d = Path(os.environ.get("DSM_EVAL_DIR", Path.home() / ".drone_search_eval")) / sid
    return json.loads((d / "ground_truth.json").read_text())


def score_findings(findings: list[dict[str, Any]], gt: dict[str, Any], t_start: float | None = None) -> dict[str, Any]:
    target = next(o for o in gt["objects"] if o["role"] == "mission_target")
    errs = [distance_m(f["lat"], f["lon"], target["lat"], target["lon"]) for f in findings]
    matched = [(e, f) for e, f in zip(errs, findings, strict=True) if e <= MATCH_RADIUS_M]
    false_reports = [f for e, f in zip(errs, findings, strict=True) if e > MATCH_RADIUS_M]
    fp_kinds = []
    for f in false_reports:
        near = min(gt["objects"], key=lambda o: distance_m(f["lat"], f["lon"], o["lat"], o["lon"]))
        dn = distance_m(f["lat"], f["lon"], near["lat"], near["lon"])
        fp_kinds.append(near["uri"].split("//")[-1] if dn < MATCH_RADIUS_M else "nothing")
    best = min(matched, key=lambda m: m[0]) if matched else None
    return {
        "found": best is not None,
        "success": best is not None and best[0] <= SUCCESS_ERROR_M,
        "position_error_m": None if best is None else round(best[0], 2),
        "false_reports": len(false_reports),
        "false_report_objects": fp_kinds,
        "n_reports": len(findings),
        "time_to_find_s": None if best is None or t_start is None else round(best[1]["reported_at"] - t_start, 1),
    }


def score_candidates(cands: list[dict[str, Any]], gt: dict[str, Any]) -> dict[str, Any]:
    """How good was the vision output before the agent decided anything?"""
    target = next(o for o in gt["objects"] if o["role"] == "mission_target")
    rank = None
    dup = 0
    for i, c in enumerate(cands):
        if distance_m(c["lat"], c["lon"], target["lat"], target["lon"]) <= MATCH_RADIUS_M:
            if rank is None:
                rank = i + 1
            else:
                dup += 1
    background = sum(
        1
        for c in cands
        if min(distance_m(c["lat"], c["lon"], o["lat"], o["lon"]) for o in gt["objects"]) > MATCH_RADIUS_M
    )
    return {
        "n_candidates": len(cands),
        "target_rank": rank,
        "target_duplicates": dup,
        "background_candidates": background,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def agg(rs: list[dict[str, Any]]) -> dict[str, Any]:
        if not rs:
            return {}
        errs = [r["position_error_m"] for r in rs if r.get("position_error_m") is not None]
        ttf = [r["time_to_find_s"] for r in rs if r.get("time_to_find_s") is not None]
        return {
            "runs": len(rs),
            "success_rate": round(sum(r["success"] for r in rs) / len(rs), 3),
            "found_rate": round(sum(r["found"] for r in rs) / len(rs), 3),
            "median_error_m": round(statistics.median(errs), 2) if errs else None,
            "max_error_m": round(max(errs), 2) if errs else None,
            "false_reports": sum(r["false_reports"] for r in rs),
            "false_reports_per_20": round(20 * sum(r["false_reports"] for r in rs) / len(rs), 2),
            "median_time_to_find_s": round(statistics.median(ttf)) if ttf else None,
            "median_battery_used_pct": _med([r.get("battery_used_pct") for r in rs]),
            "median_tool_calls": _med([r.get("tool_calls") for r in rs]),
            "target_in_candidates_rate": round(sum(r.get("target_rank") is not None for r in rs) / len(rs), 3),
            "errors": sum(1 for r in rs if r.get("error")),
        }

    # Runs that never flew (harness failures, e.g. a reference render) are not scored.
    infra = [r for r in rows if "success" not in r]
    rows = [r for r in rows if "success" in r]
    out = {"all": agg(rows)}
    if infra:
        out["all"]["infrastructure_errors_excluded"] = len(infra)
    for tier in ("easy", "medium", "hard"):
        rs = [r for r in rows if r["tier"] == tier]
        if rs:
            out[tier] = agg(rs)
    return out


def _med(xs: list[Any]) -> float | None:
    v = [x for x in xs if x is not None]
    return round(statistics.median(v), 1) if v else None


def markdown_table(summary: dict[str, Any]) -> str:
    cols = [
        "runs",
        "success_rate",
        "found_rate",
        "median_error_m",
        "max_error_m",
        "false_reports_per_20",
        "median_time_to_find_s",
        "median_battery_used_pct",
        "median_tool_calls",
        "target_in_candidates_rate",
        "errors",
    ]
    lines = ["| tier | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 1)]
    for tier, agg in summary.items():
        lines.append(f"| {tier} | " + " | ".join(str(agg.get(c)) for c in cols) + " |")
    return "\n".join(lines)
