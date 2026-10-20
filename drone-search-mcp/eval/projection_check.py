"""Projection / camera-timing calibration flight (development tool, uses known markers).

Needs the simulator up with the calibration scenario:
    scripts/sim_up.sh --scenario scenarios/fixed/calibration.json
    python eval/projection_check.py --alt 25 --speed 6

Flies back and forth over magenta 1 m markers at known positions, projects each marker
seen in each frame to GPS with the production code (vision/projection.py), and reports
the error split into along-track / cross-track, by flight direction. A sign flip of the
along-track error between directions means the frame timestamps and the pose stream are
offset in time; the script estimates that offset (error / speed).
This is the simulated equivalent of a camera-time-offset calibration on a real drone.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backends.sim import SimBackend  # noqa: E402
from common.geo import ne_between, offset  # noqa: E402
from sim.world import load_field  # noqa: E402
from vision.projection import pixel_to_ground  # noqa: E402


def markers(img: np.ndarray) -> list[tuple[float, float]]:
    r, g, b = (img[..., i].astype(int) for i in range(3))
    mask = ((r > 180) & (b > 180) & (g < 90)).astype(np.uint8)
    n, _, stats, cents = cv2.connectedComponentsWithStats(mask)
    return [
        tuple(cents[i])
        for i in range(1, n)
        if stats[i, 4] > 6
        and stats[i, 0] > 2
        and stats[i, 1] > 2
        and stats[i, 0] + stats[i, 2] < img.shape[1] - 2
        and stats[i, 1] + stats[i, 3] < img.shape[0] - 2
    ]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--alt", type=float, default=25.0)
    p.add_argument("--speed", type=float, default=6.0)
    p.add_argument("--passes", type=int, default=4)
    p.add_argument("--out", type=Path, default=ROOT / "output" / "projection_check.json")
    a = p.parse_args()
    o = load_field()["origin"]
    scen = json.loads((ROOT / "scenarios" / "fixed" / "calibration.json").read_text())
    truth = [offset(o["lat"], o["lon"], m["y"], m["x"]) for m in scen["objects"] if "cal_" in m["name"]]

    b = SimBackend()
    b.connect()
    b.set_gimbal_nadir()
    b.arm_and_takeoff(a.alt)
    while (b.telemetry().alt_rel_m or 0) < a.alt - 1:
        time.sleep(0.3)
    rows = []
    last_seq = -1
    for k in range(a.passes):
        north = 45 if k % 2 == 0 else -40
        tgt = offset(o["lat"], o["lon"], north, 0)
        b.goto(tgt[0], tgt[1], a.alt, a.speed)
        t0 = time.time()
        while time.time() - t0 < 60:
            t = b.telemetry()
            n, e = ne_between(t.lat, t.lon, *tgt)  # type: ignore[arg-type]
            if math.hypot(n, e) < 1.5:
                break
            f = b.latest_frame(1.0)
            if f is None or f.seq == last_seq:
                time.sleep(0.02)
                continue
            last_seq = f.seq
            for u, v in markers(f.image):
                g = pixel_to_ground(u, v, f.camera, f.pose, f.pose.gimbal_pitch_deg)
                if g is None:
                    continue
                best = min(truth, key=lambda tr: math.hypot(*ne_between(g.lat, g.lon, *tr)))
                en, ee = ne_between(best[0], best[1], g.lat, g.lon)  # error vector (measured - true)
                yaw = f.pose.yaw_rad
                along = en * math.cos(yaw) + ee * math.sin(yaw)
                cross = -en * math.sin(yaw) + ee * math.cos(yaw)
                spd = f.pose.groundspeed_ms
                rows.append(
                    {
                        "pass": k,
                        "dir": "N" if north > 0 else "S",
                        "speed": spd,
                        "along": along,
                        "cross": cross,
                        "err": math.hypot(en, ee),
                        "u": u,
                        "v": v,
                        "gimbal_pitch": f.pose.gimbal_pitch_deg,
                        "pitch_deg": math.degrees(f.pose.pitch_rad),
                        "roll_deg": math.degrees(f.pose.roll_rad),
                        "rate_dps": f.pose.tilt_rate_dps,
                        "lag_s": time.time() - f.wall_time,
                    }
                )
    b.return_to_launch()
    b.close()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(rows))
    moving = [r for r in rows if r["speed"] > a.speed * 0.7]
    print(f"{len(rows)} marker sightings, {len(moving)} at cruise speed")
    for d in ("N", "S"):
        rs = [r for r in moving if r["dir"] == d]
        if rs:
            al = np.array([r["along"] for r in rs])
            cr = np.array([r["cross"] for r in rs])
            sp = np.mean([r["speed"] for r in rs])
            print(
                f"heading {d}: along {al.mean():+.2f}±{al.std():.2f} m  cross {cr.mean():+.2f}±{cr.std():.2f} m  "
                f"speed {sp:.1f} m/s  => implied time offset {al.mean() / sp:+.3f} s"
            )
    for lo, hi in ((0, 2), (2, 5), (5, 10), (10, 1000)):
        rs = [r["err"] for r in rows if lo <= r["rate_dps"] < hi]
        if rs:
            print(
                f"rotation rate {lo}-{hi} deg/s: n={len(rs)} median {np.median(rs):.2f} m  p90 {np.percentile(rs, 90):.2f} m"
            )
    errs = np.array([r["err"] for r in rows])
    print(f"overall error: median {np.median(errs):.2f} m, p90 {np.percentile(errs, 90):.2f} m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
