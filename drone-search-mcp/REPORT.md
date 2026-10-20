# drone-search-mcp — status report

Simulation only (ArduCopter SITL + Gazebo Harmonic, "real-world" mode: EKF3, drifting GPS,
wind with drag, lens distortion, compressed/late/dropped video). Full history with numbers:
[EXPERIMENTS.md](EXPERIMENTS.md).

## Where it stands

| version | runs | success | median error | false reports / 20 | notes |
|---|---|---|---|---|---|
| v2 | 18 | 77.8% (easy 86%, medium 83%, hard 60%) | 1.85 m (max 4.5) | 3.3 | baseline under real-world conditions |
| v3 | 2 (stopped) | 2/2 | 1.75 m | 0 | one-shot `inspect_top` solved the red-backpack look-alike case; slow (12–16 min) |
| v4 | 2 (stopped) | 2/2 scored | 1.87 m | 0 | one run never flew (GPS drift bug, fixed) |
| v5 | 21 | 76.2% (easy 100%, medium 100%, hard 29%) | 2.03 m (max 3.26; 0.38 without GPS bias) | 2.86 | all failures: hard-tier objects under trees; 5 fixes since |

Against the targets (≥85% success, <5 m error, <2 false reports per 20): **position error is
met in every scored run** (v5 max 3.26 m). Easy and medium tiers meet every target in v5
(14/14, no false reports). The overall numbers miss because of the hard tier (2/7, three
false reports), where every failure is an object under trees; v5's traces exposed five
concrete causes, four of them now fixed (see EXPERIMENTS.md). v6 measures those fixes on new
scenarios.

## What works

* **One-command simulator** (`scripts/sim_up.sh`) with random scenarios, hidden ground truth,
  studio reference photos, and an annotated flight-video renderer.
* **High-level MCP tools**; the LLM plans and verifies, code flies. A typical mission is
  6–8 tool calls; with `execute_search(plan_id, inspect_top=N)` the agent gets search
  results and close-ups next to the reference in one call.
* **Safety layer** that holds in simulation: actuation flag, SITL proof via SIMSTATE,
  geofence + altitude band, 30% battery reserve monitor (verified to fire; a unit test caught
  a bug that would have stopped it commanding RTL), emergency_stop without locks.
* **Projection** calibrated like a real camera: measured intrinsics/distortion, measured
  frame-timing offset (separated from GPS bias by flying opposite headings), earth-locked
  gimbal model. In steady flight the remaining error is the drone's own GPS/EKF error
  (~1–2 m); the eval logs the true injected GPS bias, so each error is split into
  "GPS" and "our code" (e.g. 1.74 m total, 0.78 m without the bias).
* **Vision on CPU**: colour/contrast proposals with shadow suppression and a height-aware
  size prior, CLIP text + reference-image + colour scoring, multi-frame tracking; visual
  re-acquisition during inspection (GPS drifts between search and inspection).

## What fails or is unproven

* **Hard tier** (occlusion under trees, small targets, strong wind): 29% in v5. One target
  never became a candidate (detection under canopy, still open); the rest were inspection
  problems (narrow zoom missing the object, no zoom, spinning re-centring, beige-vs-white
  look-alikes), fixed after v5 and not yet re-measured.
* **Look-alikes** need close-ups: solved in the v3 runs we have, but on two runs only.
* **Throughput**: on this CPU-only VM the detector sees ~1–1.5 frames per sim second; a
  small target is sometimes seen only once. A GPU (or a real companion computer with an
  NPU) would allow every frame and a learned detector.
* **Simulator fidelity limits**: Gazebo graphics are cleaner than real video, terrain is
  flat, object variety is small, wind is a simple model.

## Lessons the simulator taught (each would have hit a real drone)

1. ArduPilot reports a servo gimbal's attitude relative to the airframe and its quaternion
   cannot carry roll at nadir — use the earth-locked target when the lock flags are set.
2. SITL's default `AHRS_EKF_TYPE 10` is a perfect pose; it hid gimbal and timing bugs.
3. GPS drifts between search and inspection: inspections must re-acquire visually.
4. A video pipeline that cannot keep up must drop frames, not queue them; stamp frames at
   capture + known latency.
5. The battery model: SITL+JSON reports no current; without a model the reserve never fires.

## Before a real-drone test

1. **RealBackend**: the ArduPilot MAVLink code is shared with SITL; add the payload's video
   source (RTSP/UDP) with timestamps relatable to the autopilot clock, and its zoom/camera
   control (MAV_CMD_SET_CAMERA_ZOOM or the vendor SDK). Tello needs its own backend.
2. **Calibrate on the aircraft**: intrinsics/distortion per zoom step, camera-time offset with
   the opposite-heading method (`eval/projection_check.py` against ground markers), gimbal
   behaviour (does it report earth-locked roll/pitch? measured or commanded angles?).
3. **Position accuracy**: plan for 1–3 m GPS error, or fit RTK, or reference a ground
   control point; use a rangefinder or terrain data instead of flat ground.
4. **Safety for real**: keep the actuation flag and SITL check, add an explicit
   `--allow-real-vehicle` with a human-confirmed geofence, a pilot with RC override,
   obstacle-aware inspection altitudes (the 12 m floor assumes no tall obstacles),
   lost-link and lost-video behaviour (the GCS-heartbeat failsafe is already enabled).
5. **Finish the eval loop**: run `scripts/eval_snapshot.sh v6 --n 21`
   and continue until the targets hold on fresh scenarios; then fly small, open-field,
   large-target missions first.

## Environment note

In the final hours of this session the cloud VM's memory became pathologically slow for
fresh allocations (≈20 MB/s; a CLIP forward pass went from 0.32 s to 24.5 s, and even the
stock ardupilot_gazebo world could not keep SITL in lockstep). Guest metrics were normal and
freeing caches/artifacts did not help. After a machine restart it was healthy again, and v4/v5 ran normally.
