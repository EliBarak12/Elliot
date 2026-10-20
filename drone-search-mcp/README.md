# drone-search-mcp

An MCP server that lets an AI agent take a reference photo (or a text description) of an
object, fly a drone over an area, find the object from above, and report its GPS position
with a photo as proof.

**Simulation only.** The server refuses to move any vehicle that does not prove it is
ArduPilot SITL. The backend interface is built so a real ArduPilot drone (and later a
Tello) can be added without touching the tools; see [REPORT.md](REPORT.md) for what that
still needs.

The LLM plans, code flies: tools are high-level (`plan_search`, `execute_search`,
`inspect_candidate`, ...), the coverage pattern, per-frame detection, GPS projection and
deduplication all run in code, and the LLM is only asked to make the final yes/no call on
a close-up image.

## Setup (Ubuntu 24.04, x86_64)

```bash
scripts/setup.sh
```

Installs Gazebo Harmonic, the prebuilt ArduCopter SITL, the `ardupilot_gazebo` plugin, a
Python 3.12 venv (CPU torch, FastMCP, pymavlink, transformers), builds the simulation
assets (procedural field, nadir-gimbal drone, Gazebo Fuel models) and downloads the vision
weights (CLIP ViT-B/32, OWL-ViT B/32, DINOv2-small). No GPU needed; Gazebo renders with
Mesa llvmpipe.

## Demo

```bash
scripts/demo.sh medium        # random scenario -> Claude flies it -> score + flight.mp4
```

Or step by step:

```bash
source scripts/env.sh
.venv/bin/python scenarios/generate.py --tier medium --seed 7      # random scenario
scripts/sim_up.sh --scenario scenarios/runs/medium-0007/scenario.json
claude mcp add drone-search -- "$PWD/.venv/bin/python" -m server --allow-actuation
claude    # "Find the object in scenarios/runs/medium-0007/reference.png inside <polygon>"
.venv/bin/python scripts/make_video.py output/<timestamp>      # annotated flight video
scripts/sim_down.sh
```

`.mcp.json` in this directory already registers the server for Claude Code.

## Layout

```
server/      FastMCP server: tools, safety gate, planner, mission runner, flight recorder
backends/    DroneBackend interface; ArduPilot/MAVLink (SITL now, hardware later); fake backend for tests
vision/      proposals, CLIP/OWL/DINO models, target matcher, pixel->GPS projection, candidate tracker
common/      geodesy (ArduPilot-compatible flat-earth maths)
sim/         world generator, model/asset builder, launcher, frame bridge, SITL params, Lua battery
scenarios/   random scenario generator (+ fixed calibration scenario)
eval/        eval harness (Claude as the agent), scoring, projection calibration, CLI tool caller
scripts/     setup, sim_up/sim_down, demo, make_video
tests/       unit tests (pytest; no simulator needed)
```

## Tools

| tool | what it does |
|---|---|
| `get_status` | live state (position, altitude, battery, mode, armed), safety limits, target, plans, top candidates, findings |
| `set_search_target(image_path?, text?, object_size_m?)` | stores the reference, computes CLIP embeddings and colour histogram; infers a label from the photo when no text is given |
| `plan_search(area_polygon \| center+radius, altitude_m?, overlap, pattern, speed_ms)` | lawnmower or spiral sized from the camera footprint; picks altitude so the target spans ≥22 px; returns time and battery estimates and whether it fits the geofence and reserve |
| `execute_search(plan_id)` | takes off if needed, flies the pattern, analyses every frame it can, returns ranked deduplicated candidates (GPS, confidence, cues, thumbnail) |
| `inspect_candidate(candidate_id)` | flies over, descends in two steps while re-centring on the object, returns a close-up image and refined GPS |
| `capture_image` | current camera frame |
| `goto(lat, lon, alt_m)`, `return_home`, `land` | blocking moves that return state when done |
| `emergency_stop(kill_motors=false)` | brake/hover (or cut motors); never blocked by a running routine |
| `report_finding(candidate_id, confidence, notes)` | records the result (GPS + photo) to `findings.json` |

Every response ends with `state` read from live telemetry after the action. Errors are
`{"error": {"code", "message", "next_step"}}`.

## Safety (kept in simulation too)

Design studied from [mavlink-mcp](https://github.com/deepak61296/mavlink-mcp) (MIT); the
code here is our own.

* **Actuation is opt-in**: without `--allow-actuation` only read-only tools work.
* **Refuse if not SITL**: the vehicle must stream `SIMSTATE` (real firmware never does);
  the connection string is never trusted for this.
* **Geofence**: every commanded point must be within 250 m of home (optional polygon);
  plans that leave it are refused before take-off. ArduPilot's own fence is enabled
  underneath (`FENCE_*`), plus the GCS-heartbeat failsafe (RTL if the server dies).
* **Altitude band** 8–60 m for flight legs; nonsense arguments are refused, not clamped.
* **Battery reserve**: a monitor aborts any routine and returns to launch at 30%; plans
  that would end below the reserve are refused up front.
* **emergency_stop** is fire-and-forget on the MAVLink socket, never waits on a lock.
* **Ground truth isolation**: scenario ground truth lives in `$DSM_EVAL_DIR`
  (`~/.drone_search_eval`), which the server refuses to read; it only reads camera frames,
  never simulator object poses.

## Simulation

* Gazebo Harmonic, headless, CPU rendering. Procedural 400×400 m field (grass tiles,
  asphalt roads, a dirt track), Fuel houses and trees, launch pad.
* Drone: Iris with a 3-axis servo gimbal (from `ardupilot_gazebo`) carrying a 1280×960
  nadir camera (HFOV 1.2 rad) at 5 Hz. ArduPilot stabilises the gimbal in earth frame.
* ArduCopter SITL in lockstep over the JSON interface. SITL+JSON reports no battery current,
  so `sim/scripts/sim_battery.lua` models it from the motor outputs (≈6.6 %/min cruise).
* Scenarios (`scenarios/generate.py`): 1–3 targets (red backpack, blue car, person, white
  box) at random positions, look-alike distractors (other red backpacks, red boxes, blue
  containers/tarps, other cars and people, beige/cardboard boxes...). Hard tier adds
  partial occlusion under trees or a smaller target, plus wind. Reference photos are
  rendered from a random oblique angle in a neutral studio, so they never look like the
  aerial view.

## Evaluation

```bash
.venv/bin/python eval/run.py --n 20 --version v3 --tiers easy,medium,hard
```

Runs N fresh scenarios headless with Claude as the agent (Messages API when
`ANTHROPIC_API_KEY` is set, otherwise headless Claude Code with only the MCP tools
enabled), scores reports against ground truth and writes `eval/results/<version>/`.
History and metrics per version: [EXPERIMENTS.md](EXPERIMENTS.md). Summary and open
problems: [REPORT.md](REPORT.md).

## Tests

```bash
.venv/bin/python -m pytest -q        # unit tests, no simulator
.venv/bin/ruff check . && .venv/bin/python -m mypy server backends vision common
```

## Licences

Code: MIT. The drone model is derived at setup time from `ardupilot_gazebo` (LGPL-3) and
not redistributed; Gazebo Fuel models are downloaded from fuel.gazebosim.org under their
own licences (mostly CC-BY 4.0).
