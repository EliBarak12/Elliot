"""Generate random search scenarios.

    python scenarios/generate.py --tier medium --seed 7 [--target red_backpack] [--no-render]

Writes two halves that must never meet:

* ``scenarios/runs/<id>/``  - public: ``scenario.json`` (world objects for the simulator,
  no labels), ``mission.json`` (what the agent is told: target description, reference
  image, search area) and ``reference.png``.
* ``$DSM_EVAL_DIR/<id>/ground_truth.json`` - private: which object is the target and the
  true GPS of every target and distractor. Only ``eval/`` reads it. The MCP server refuses
  to open anything under ``$DSM_EVAL_DIR``.

Tiers:
    easy    1 target, open field, no distractors, 80 m square
    medium  1-3 targets (one is the mission target), 3-6 look-alike distractors, 100 m
    hard    medium + partial occlusion under trees or a small target, wind, 120 m
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from common.geo import offset  # noqa: E402
from sim.world import blocked, load_field, tree_positions  # noqa: E402

# Target catalogue. "lookalikes" share colour or category with the target and are the
# interesting distractors; "others" are generic clutter.
TARGETS: dict[str, dict[str, Any]] = {
    "red_backpack": {
        "uri": "model://red_backpack",
        "text": "a red backpack lying on the ground",
        "size_m": 0.5,
        "ref": {"dist": 2.2, "pitch": (20, 45)},
        "lookalikes": [
            "model://red_backpack_2",
            "model://blue_backpack",
            "model://red_box",
            "model://red_bucket",
            "model://suitcase",
        ],
    },
    "blue_car": {
        "uri": "model://blue_car",
        "text": "a blue hatchback car",
        "size_m": 4.2,
        "ref": {"dist": 11.0, "pitch": (12, 35)},
        "lookalikes": [
            "model://red_car",
            "model://white_car",
            "model://suv",
            "model://pickup",
            "model://blue_container",
            "model://blue_tarp",
        ],
    },
    "person": {
        "uri": "model://person_standing",
        "text": "a person in a white t-shirt and blue jeans",
        "size_m": 0.6,
        "ref": {"dist": 4.5, "pitch": (5, 25)},
        "lookalikes": ["model://person_casual", "model://white_cylinder", "model://postbox"],
    },
    "white_box": {
        "uri": "model://white_box",
        "text": "a white box about 60 cm wide",
        "size_m": 0.6,
        "ref": {"dist": 2.5, "pitch": (25, 50)},
        "lookalikes": [
            "model://beige_box",
            "model://cardboard_box",
            "model://white_cylinder",
            "model://grey_box",
            "model://white_car",
        ],
    },
}
SMALL_VARIANT = {"white_box": "model://small_white_box"}
TIERS: dict[str, dict[str, Any]] = {
    "easy": {"side_m": 80, "n_targets": (1, 1), "n_distractors": (0, 0), "wind": False},
    "medium": {"side_m": 100, "n_targets": (1, 3), "n_distractors": (3, 6), "wind": False},
    "hard": {"side_m": 120, "n_targets": (1, 3), "n_distractors": (4, 7), "wind": True},
}


def eval_dir() -> Path:
    return Path(os.environ.get("DSM_EVAL_DIR", Path.home() / ".drone_search_eval"))


def _place(
    rng: np.random.Generator,
    field: dict[str, Any],
    cx: float,
    cy: float,
    half: float,
    taken: list[tuple[float, float]],
    road_ok: bool,
    near_tree: bool = False,
) -> tuple[float, float]:
    trees = tree_positions(field)
    for _ in range(4000):
        if near_tree:
            _, tx, ty, _ = trees[int(rng.integers(0, len(trees)))]
            if not (abs(tx - cx) < half - 3 and abs(ty - cy) < half - 3):
                continue
            ang, r = rng.uniform(0, 2 * math.pi), rng.uniform(1.2, 2.5)
            x, y = tx + r * math.cos(ang), ty + r * math.sin(ang)
        else:
            x, y = cx + rng.uniform(-half + 3, half - 3), cy + rng.uniform(-half + 3, half - 3)
            if blocked(field, x, y, 3.0, trees=trees, road_ok=road_ok):
                continue
        if any(math.hypot(x - a, y - b) < 8 for a, b in taken):
            continue
        if math.hypot(x, y) < 10:  # keep the launch pad clear
            continue
        return float(x), float(y)
    raise RuntimeError("could not place object; area too crowded")


def generate(
    tier: str, seed: int, target: str | None = None, mode: str = "both", real_world: bool = True
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    cfg = TIERS[tier]
    field = load_field()
    o = field["origin"]
    sid = f"{tier}-{seed:04d}"
    half = cfg["side_m"] / 2
    cx, cy = rng.uniform(-25, 25, 2)

    mission_key = target or str(rng.choice(sorted(TARGETS)))
    others = [k for k in sorted(TARGETS) if k != mission_key]
    n_t = int(rng.integers(cfg["n_targets"][0], cfg["n_targets"][1] + 1))
    target_keys = [mission_key] + list(rng.choice(others, size=n_t - 1, replace=False))

    hard_twist = None
    if tier == "hard":
        hard_twist = "small" if mission_key in SMALL_VARIANT and rng.random() < 0.4 else "occluded"

    objects: list[dict[str, Any]] = []
    truth: list[dict[str, Any]] = []
    taken: list[tuple[float, float]] = []
    for i, key in enumerate(target_keys):
        spec = TARGETS[key]
        uri = spec["uri"]
        if i == 0 and hard_twist == "small":
            uri = SMALL_VARIANT[key]
        x, y = _place(
            rng, field, cx, cy, half, taken, road_ok=key == "blue_car", near_tree=(i == 0 and hard_twist == "occluded")
        )
        taken.append((x, y))
        name = f"obj_{len(objects):02d}"
        objects.append({"name": name, "uri": uri, "x": x, "y": y, "yaw": float(rng.uniform(0, 6.283))})
        lat, lon = offset(o["lat"], o["lon"], y, x)
        truth.append(
            {
                "name": name,
                "kind": key,
                "uri": uri,
                "role": "mission_target" if i == 0 else "other_target",
                "x": x,
                "y": y,
                "lat": lat,
                "lon": lon,
            }
        )

    n_d = int(rng.integers(cfg["n_distractors"][0], cfg["n_distractors"][1] + 1))
    pool = list(TARGETS[mission_key]["lookalikes"])
    for _ in range(n_d):
        uri = str(rng.choice(pool))
        x, y = _place(rng, field, cx, cy, half, taken, road_ok="car" in uri or "suv" in uri)
        taken.append((x, y))
        name = f"obj_{len(objects):02d}"
        objects.append({"name": name, "uri": uri, "x": x, "y": y, "yaw": float(rng.uniform(0, 6.283))})
        lat, lon = offset(o["lat"], o["lon"], y, x)
        truth.append(
            {
                "name": name,
                "kind": "distractor",
                "uri": uri,
                "role": "distractor",
                "x": x,
                "y": y,
                "lat": lat,
                "lon": lon,
            }
        )

    # shuffle names so object order in the world file says nothing about roles
    perm = rng.permutation(len(objects))
    for new_i, old_i in enumerate(perm):
        objects[old_i]["name"] = truth[old_i]["name"] = f"obj_{new_i:02d}"
    objects.sort(key=lambda d: d["name"])

    # Real-world conditions (default): every tier gets a breeze, sensor noise and a degraded
    # camera; hard adds strong gusty wind. --ideal turns all of it off.
    wind = None
    realism = None
    sun = {"sun_dir": "-0.4 0.3 -0.9", "sun_intensity": 0.9}
    if cfg["wind"]:
        wind = {
            "speed_ms": float(rng.uniform(4, 8)),
            "dir_deg": float(rng.uniform(0, 360)),
            "turbulence": float(rng.uniform(0.5, 1.5)),
        }
    if real_world:
        if wind is None:
            wind = {
                "speed_ms": float(rng.uniform(0.5, 3.0)),
                "dir_deg": float(rng.uniform(0, 360)),
                "turbulence": float(rng.uniform(0.2, 0.6)),
            }
        el, az = rng.uniform(25, 70), rng.uniform(0, 360)
        sun = {
            "sun_dir": " ".join(
                f"{v:.3f}"
                for v in (
                    -math.cos(math.radians(el)) * math.sin(math.radians(az)),
                    -math.cos(math.radians(el)) * math.cos(math.radians(az)),
                    -math.sin(math.radians(el)),
                )
            ),
            "sun_intensity": float(rng.uniform(0.65, 1.0)),
        }
        realism = {
            "camera": {
                "enabled": True,
                "jpeg_quality": int(rng.integers(55, 85)),
                "noise_sigma": float(rng.uniform(1.5, 4.5)),
                "exposure_s": float(rng.uniform(0.003, 0.010)),
                "vignette": float(rng.uniform(0.15, 0.35)),
                "gain_walk": 0.01,
                "latency_s": float(rng.uniform(0.17, 0.23)),
                "latency_jitter_s": 0.03,
                "drop_prob": float(rng.uniform(0.02, 0.10)),
            },
            "nav": {
                "gps_noise_m": float(rng.uniform(0.2, 0.6)),
                "baro_noise_m": float(rng.uniform(0.1, 0.4)),
                "gps_alt_drift_m": 0.0,
                "gps_bias_sigma_m": float(rng.uniform(0.8, 2.0)),
                "gps_bias_tau_s": float(rng.uniform(60, 240)),
                "seed": int(rng.integers(1, 10_000)),
            },
        }
    corners_xy = [(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half)]
    polygon = [list(offset(o["lat"], o["lon"], y, x)) for x, y in corners_xy]

    run_dir = HERE / "runs" / sid
    run_dir.mkdir(parents=True, exist_ok=True)
    spec = TARGETS[mission_key]
    scenario = {"id": sid, "objects": objects, "wind": wind, "realism": realism, **sun}
    mission = {
        "id": sid,
        "tier": tier,
        "target_text": spec["text"] if mode in ("text", "both") else None,
        "reference_image": str(run_dir / "reference.png") if mode in ("image", "both") else None,
        "search_area": {"polygon_latlon": polygon},
        "home": {"lat": o["lat"], "lon": o["lon"]},
    }
    (run_dir / "scenario.json").write_text(json.dumps(scenario, indent=2))
    (run_dir / "mission.json").write_text(json.dumps(mission, indent=2))

    gt_dir = eval_dir() / sid
    gt_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(gt_dir.parent, 0o700)
    ground_truth = {
        "id": sid,
        "tier": tier,
        "seed": seed,
        "mission_target_kind": mission_key,
        "hard_twist": hard_twist,
        "wind": wind,
        "objects": truth,
        "area_center_xy": [float(cx), float(cy)],
        "area_side_m": cfg["side_m"],
    }
    (gt_dir / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2))
    return {
        "id": sid,
        "run_dir": str(run_dir),
        "mission": mission,
        "ref_spec": spec["ref"],
        "uri": spec["uri"],
        "rng_state": int(rng.integers(0, 2**31)),
    }


def render_reference(info: dict[str, Any]) -> bool:
    rng = np.random.default_rng(info["rng_state"])
    ref = info["ref_spec"]
    out = Path(info["run_dir"]) / "reference.png"
    cmd = [
        os.environ.get("DSM_SYS_PYTHON", "/usr/bin/python3.12"),
        str(ROOT / "sim" / "render_studio.py"),
        "--model",
        info["uri"],
        "--out",
        str(out),
        "--dist",
        f"{ref['dist'] * rng.uniform(0.9, 1.2):.2f}",
        "--pitch",
        f"{rng.uniform(*ref['pitch']):.1f}",
        "--yaw",
        f"{rng.uniform(0, 360):.1f}",
    ]
    return subprocess.run(cmd, capture_output=True, timeout=240).returncode == 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tier", choices=sorted(TIERS), default="easy")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--target", choices=sorted(TARGETS))
    p.add_argument("--mode", choices=["image", "text", "both"], default="both")
    p.add_argument("--no-render", action="store_true")
    p.add_argument("--ideal", action="store_true", help="perfect sensors, no wind (debugging only)")
    a = p.parse_args()
    info = generate(a.tier, a.seed, a.target, a.mode, real_world=not a.ideal)
    if not a.no_render and a.mode != "text" and not render_reference(info):
        print("[scenario] reference render failed", file=sys.stderr)
        return 1
    print(json.dumps({"id": info["id"], "run_dir": info["run_dir"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
