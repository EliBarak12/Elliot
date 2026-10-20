"""Offline vision benchmark: replay recorded search frames through the analyser + tracker.

    DSM_SAVE_FRAMES=1 python eval/run.py ...           # records full-res frames per run
    python eval/vision_bench.py eval/results/v1 [--min-score 0.3] [--set proposals.k_sigma=2.5]

For every run directory with server/frames/, rebuilds the search target from the mission
(same text + reference image the agent used), replays frames in order, and scores the
resulting candidates against ground truth: is the target found, at which rank, how many
duplicates and background candidates. Lets vision changes be compared on many recorded
scenarios without re-flying them (the flight path is fixed, so this measures vision only).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backends.base import CameraModel, Frame, Telemetry  # noqa: E402
from common.geo import distance_m  # noqa: E402
from eval.score import MATCH_RADIUS_M, ground_truth  # noqa: E402
from vision.matcher import build_target  # noqa: E402
from vision.pipeline import AnalyzerConfig, CandidateTracker, FrameAnalyzer  # noqa: E402


def apply_overrides(cfg: AnalyzerConfig, sets: list[str]) -> AnalyzerConfig:
    for s in sets:
        key, val = s.split("=", 1)
        obj: Any = cfg
        parts = key.split(".")
        for part in parts[:-1]:
            obj = getattr(obj, part)
        setattr(obj, parts[-1], type(getattr(obj, parts[-1]))(val))
    return cfg


def bench_run(run_dir: Path, cfg: AnalyzerConfig) -> dict[str, Any] | None:
    frames_dir = run_dir / "server" / "frames"
    if not (frames_dir / "frames.jsonl").exists():
        return None
    sid = run_dir.name
    mission = json.loads((ROOT / "scenarios" / "runs" / sid / "mission.json").read_text())
    ref = np.asarray(Image.open(mission["reference_image"]).convert("RGB")) if mission.get("reference_image") else None
    target = build_target(mission.get("target_text"), ref)
    analyzer = FrameAnalyzer(target, cfg)
    tracker = CandidateTracker(merge_radius_m=max(3.0, target.size_m * 0.75))
    for line in (frames_dir / "frames.jsonl").read_text().splitlines():
        rec = json.loads(line)
        img = np.asarray(Image.open(frames_dir / rec["file"]).convert("RGB"))
        pose = Telemetry(**{k: v for k, v in rec["pose"].items() if k in Telemetry.__dataclass_fields__})
        f = Frame(img, CameraModel(**rec["camera"]), rec["seq"], rec["t"], 0.0, pose)
        tracker.note_coverage(f)
        tracker.add(analyzer.analyze(f))
    gt = ground_truth(sid)
    tgt = next(o for o in gt["objects"] if o["role"] == "mission_target")
    cands = tracker.ranked()
    rank, dups, err = None, 0, None
    for i, c in enumerate(cands):
        d = distance_m(c.lat, c.lon, tgt["lat"], tgt["lon"])
        if d <= MATCH_RADIUS_M:
            if rank is None:
                rank, err = i + 1, d
            else:
                dups += 1
    background = sum(
        1 for c in cands if min(distance_m(c.lat, c.lon, o["lat"], o["lon"]) for o in gt["objects"]) > MATCH_RADIUS_M
    )
    distractor_above = sum(1 for c in cands[: (rank or len(cands) + 1) - 1])
    return {
        "id": sid,
        "tier": gt["tier"],
        "kind": gt["mission_target_kind"],
        "twist": gt.get("hard_twist"),
        "n_cands": len(cands),
        "target_rank": rank,
        "target_err_m": None if err is None else round(err, 2),
        "target_conf": None if rank is None else round(cands[rank - 1].confidence, 3),
        "ranked_above_target": distractor_above,
        "dups": dups,
        "background": background,
        "skipped_unsteady": analyzer.skipped_unsteady,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("results_dir", type=Path, nargs="+")
    p.add_argument("--set", action="append", default=[], help="AnalyzerConfig override, e.g. proposals.k_sigma=2.5")
    a = p.parse_args()
    rows = []
    for rd in a.results_dir:
        for run in sorted(d for d in rd.iterdir() if d.is_dir()):
            r = bench_run(run, apply_overrides(AnalyzerConfig(), a.set))
            if r:
                rows.append(r)
                print(json.dumps(r), flush=True)
    if rows:
        found = sum(r["target_rank"] is not None for r in rows)
        top1 = sum(r["target_rank"] == 1 for r in rows)
        print(
            f"\n{len(rows)} runs: target in candidates {found}/{len(rows)}, rank 1 {top1}/{len(rows)}, "
            f"mean candidates {np.mean([r['n_cands'] for r in rows]):.1f}, "
            f"background {sum(r['background'] for r in rows)}, duplicates {sum(r['dups'] for r in rows)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
