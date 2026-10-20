"""Render flight recordings into an annotated MP4: drone camera (left) + live map (right).

    python scripts/make_video.py OUTPUT_DIR [--out flight.mp4] [--fps 8] [--truth ground_truth.json]

OUTPUT_DIR is the server's --output directory (it contains recording/<segment>/...).
All segments (searches, inspections, gotos) are concatenated in time order. ``--truth``
(evaluation only) draws the true object positions on the map.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common.geo import ne_between  # noqa: E402

MAP = 480
CAM_W, CAM_H = 640, 480


class MapView:
    def __init__(self, home: tuple[float, float], pts: list[tuple[float, float]]) -> None:
        self.home = home
        ne = [ne_between(home[0], home[1], la, lo) for la, lo in pts] + [(0.0, 0.0)]
        ns, es = zip(*ne, strict=True)
        self.cn, self.ce = (max(ns) + min(ns)) / 2, (max(es) + min(es)) / 2
        span = max(max(ns) - min(ns), max(es) - min(es), 40) * 1.15
        self.scale = (MAP - 40) / span

    def px(self, lat: float, lon: float) -> tuple[int, int]:
        n, e = ne_between(self.home[0], self.home[1], lat, lon)
        return int(MAP / 2 + (e - self.ce) * self.scale), int(MAP / 2 - (n - self.cn) * self.scale)


def hud(img: np.ndarray, rec: dict[str, Any], title: str) -> None:
    lines = [
        title,
        f"alt {rec.get('alt') or 0:5.1f} m   speed {rec.get('speed') or 0:4.1f} m/s",
        f"battery {rec.get('battery') or 0:5.1f}%   mode {rec.get('mode')}",
    ]
    cv2.rectangle(img, (0, 0), (CAM_W, 64), (0, 0, 0), -1)
    for i, s in enumerate(lines):
        cv2.putText(img, s, (8, 18 + 20 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    cx, cy = CAM_W // 2, CAM_H // 2
    cv2.line(img, (cx - 8, cy), (cx + 8, cy), (255, 255, 255), 1)
    cv2.line(img, (cx, cy - 8), (cx, cy + 8), (255, 255, 255), 1)


def render(out_dir: Path, out: Path, fps: float, truth: dict[str, Any] | None) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    segs = sorted(p for p in (out_dir / "recording").glob("*") if (p / "telemetry.jsonl").exists())
    if not segs:
        print("no recordings under", out_dir / "recording")
        return 1
    recs: list[tuple[Path, dict[str, Any]]] = []
    ctx: dict[str, Any] = {}
    for s in segs:
        for line in (s / "telemetry.jsonl").read_text().splitlines():
            r = json.loads(line)
            r["_title"] = s.name.split("_", 1)[1]
            recs.append((s, r))
        if (s / "context.json").exists():
            ctx = json.loads((s / "context.json").read_text())  # last one has the most candidates
    recs = [(s, r) for s, r in recs if r.get("lat") is not None]
    home = tuple(ctx.get("home") or (recs[0][1]["lat"], recs[0][1]["lon"]))
    plans = ctx.get("plans") or {}
    pts = [(r["lat"], r["lon"]) for _, r in recs]
    for p in plans.values():
        pts += [tuple(x) for x in p["area"]]
    view = MapView(home, pts)  # type: ignore[arg-type]
    base = np.full((MAP, MAP, 3), 30, np.uint8)
    for p in plans.values():
        poly = np.array([view.px(*a) for a in p["area"]], np.int32)
        cv2.polylines(base, [poly], True, (90, 160, 90), 1, cv2.LINE_AA)
        wps = np.array([view.px(*w) for w in p["waypoints"]], np.int32)
        cv2.polylines(base, [wps], False, (70, 70, 110), 1, cv2.LINE_AA)
    if truth:
        for o in truth["objects"]:
            col = (0, 220, 255) if o["role"] == "mission_target" else (120, 120, 120)
            x, y = view.px(o["lat"], o["lon"])
            cv2.drawMarker(
                base, (x, y), col, cv2.MARKER_STAR if o["role"] == "mission_target" else cv2.MARKER_TILTED_CROSS, 12, 1
            )
    hx, hy = view.px(*home)  # type: ignore[arg-type]
    cv2.circle(base, (hx, hy), 5, (200, 200, 200), 1)
    cv2.putText(base, "H", (hx + 6, hy + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

    ff = subprocess.Popen(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{CAM_W + MAP}x{CAM_H}",
            "-r",
            str(fps),
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "23",
            str(out),
        ],
        stdin=subprocess.PIPE,
    )
    assert ff.stdin is not None
    track: list[tuple[int, int]] = []
    cands = ctx.get("candidates") or []
    findings = {f["candidate_id"] for f in ctx.get("findings") or []}
    for seg, r in recs:
        img = cv2.imread(str(seg / "frames" / r["frame"]))
        if img is None:
            continue
        for d in r.get("dets", []):
            x0, y0, x1, y1 = (int(v) for v in d["bbox"])
            col = (0, 0, 255) if d["score"] > 0.5 else (0, 200, 255)
            cv2.rectangle(img, (x0 - 3, y0 - 3), (x1 + 3, y1 + 3), col, 2)
            cv2.putText(
                img, f"{d['score']:.2f}", (x0, max(10, y0 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA
            )
        hud(img, r, f"{r['_title']}  target: {ctx.get('target') or '-'}")
        m = base.copy()
        track.append(view.px(r["lat"], r["lon"]))
        if len(track) > 1:
            cv2.polylines(m, [np.array(track, np.int32)], False, (255, 200, 0), 1, cv2.LINE_AA)
        for c in cands:
            x, y = view.px(c["lat"], c["lon"])
            col = (0, 255, 0) if c["id"] in findings else (0, 0, 255) if c["confidence"] > 0.5 else (0, 160, 255)
            cv2.circle(m, (x, y), 4, col, -1)
            cv2.putText(m, c["id"], (x + 5, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, col, 1)
        x, y = track[-1]
        yaw = r.get("yaw") or 0.0
        tip = (int(x + 10 * math.sin(yaw)), int(y - 10 * math.cos(yaw)))
        cv2.arrowedLine(m, (x, y), tip, (255, 255, 255), 2, tipLength=0.5)
        cv2.putText(
            m,
            "map: search area (green), plan (purple), track (blue)",
            (6, MAP - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (180, 180, 180),
            1,
        )
        ff.stdin.write(np.hstack([img, m]).tobytes())
    ff.stdin.close()
    ff.wait()
    print(f"wrote {out} ({len(recs)} frames, {len(recs) / fps:.0f} s at {fps:g} fps)")
    return ff.returncode


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("output_dir", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--fps", type=float, default=8.0)
    p.add_argument("--truth", type=Path)
    a = p.parse_args()
    truth = json.loads(a.truth.read_text()) if a.truth else None
    return render(a.output_dir, a.out or a.output_dir / "flight.mp4", a.fps, truth)


if __name__ == "__main__":
    sys.exit(main())
