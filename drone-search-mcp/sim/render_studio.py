"""Render a photo of one object in a neutral studio (reference images, asset previews).

    python sim/render_studio.py --model "JanSport Backpack Red" --out ref.png \
        [--dist 2.5 --pitch 30 --yaw 35]

Needs scripts/env.sh sourced (Gazebo resource paths).
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from sim.world import studio_sdf  # noqa: E402


def render(model: str, out: Path, dist: float, pitch_deg: float, yaw_deg: float) -> bool:
    with tempfile.TemporaryDirectory() as td:
        world = Path(td) / "studio.sdf"
        world.write_text(studio_sdf(model, dist, math.radians(pitch_deg), math.radians(yaw_deg)))
        env = dict(os.environ)
        env["GZ_PARTITION"] = f"studio_{os.getpid()}"
        gz = subprocess.Popen(
            ["gz", "sim", "-s", "-r", "--headless-rendering", str(world)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            r = subprocess.run(
                [
                    env.get("DSM_SYS_PYTHON", "/usr/bin/python3.12"),
                    str(HERE / "frame_grabber.py"),
                    "--topic",
                    "/studio/camera",
                    "--once",
                    str(out),
                    "--skip",
                    "4",
                ],
                env=env,
                timeout=180,
            )
            return r.returncode == 0
        finally:
            gz.terminate()
            try:
                gz.wait(10)
            except subprocess.TimeoutExpired:
                gz.kill()
            time.sleep(0.5)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--dist", type=float, default=3.0)
    p.add_argument("--pitch", type=float, default=30.0)
    p.add_argument("--yaw", type=float, default=35.0)
    a = p.parse_args()
    return 0 if render(a.model, a.out, a.dist, a.pitch, a.yaw) else 1


if __name__ == "__main__":
    sys.exit(main())
