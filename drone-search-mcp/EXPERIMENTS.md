# EXPERIMENTS

Improvement history of drone-search-mcp. Every version is evaluated on **fresh random
scenarios** (new seeds), never on the scenario that motivated the change. Metrics come from
`eval/run.py` (Claude as the agent, ground truth hidden from the server) unless noted.

Success = a reported position within 5 m of the mission target. False report = a report more
than 10 m from the target. Target: ≥85% success, <5 m error, <2 false reports per 20 runs,
across easy / medium / hard.

---

## v0 — bring-up findings (before any agent eval)

Things the simulator taught us before the first scored run. Each one would have silently
corrupted every later metric.

### Projection calibration
`eval/projection_check.py` flies back and forth over 1 m magenta markers at known positions
and projects every sighting with the production code.

| condition | sightings | median error | p90 |
|---|---|---|---|
| hover, nadir, 25 m | 1 frame | 0 px off (10 m marker at +374 px, predicted 374) | — |
| all frames, gimbal in NEUTRAL mode | 224 | 0.20 m | 3.74 m |
| body rotation rate < 2 °/s | 301 | 0.22 m | 0.57 m |
| body rotation rate 5–10 °/s | 9 | 4.09 m | 5.61 m |

* **Gimbal was not stabilising.** `MNT1_DEFLT_MODE` NEUTRAL holds *body-frame* angles, so
  the camera pitched with the airframe (up to 20° while accelerating: ~9 m error at 25 m).
  Fix: command earth-frame MAVLink targeting at −90° before take-off. Note that ArduPilot's
  reported gimbal attitude for a servo gimbal is the *commanded* angle, so it never showed
  the problem.
* **Even stabilised, frames during attitude transients are wrong by metres** (servo lag +
  render latency). Fix: the analyser skips frames while the body rotates faster than
  3 °/s. These only occur at lane ends, which the lane overlap covers anyway.
* Frame↔pose timing: SITL in lockstep with Gazebo runs on the physics clock, so the image
  stamp and `time_boot_ms` share a timebase. Residual along-track bias +0.3 m at 6 m/s
  (≈50 ms), not worth correcting yet.

### Battery never drained
SITL's JSON (Gazebo) physics backend reports 0 A, so the battery sat at 100% and the 30%
reserve could never trigger. Fix: `sim/scripts/sim_battery.lua`, an ArduPilot scripting
battery backend that models current from the four motor outputs (cruise ≈13 A on 3.3 Ah,
≈6.6 %/min). The autopilot then reports battery exactly as a power module would.

### Safety monitor bug caught by tests
`log.warning("safety.event", event=msg)` collides with structlog's positional `event`, so
the reserve monitor threw *before* commanding RTL. Unit test `test_reserve_monitor_triggers_rtl`
caught it; RTL is now commanded before any bookkeeping.

---

## Self-play session 1 (me as the agent, medium-0011, red backpack)

Flown by hand through `eval/call.py` against the HTTP transport, using only the MCP tools.

| found | position error | time | battery | false reports | tool calls |
|---|---|---|---|---|---|
| yes | 0.1 m | 348 s | 33% | 0 | 8 |

Flow: get_status → set_search_target (image + text) → plan_search (server chose 21 m,
target ≈22 px) → execute_search (171 s, 11 candidates) → inspect c4 → inspect c9 →
report c4 → return_home.

What was confusing / hard:
1. `times_seen` (26) larger than `frames_covering_spot` (15) for one candidate: one frame
   produced several blobs (object + shadow) that all counted. Contradictory numbers make an
   agent distrust the confidence field.
2. `position_spread_m` exactly 0.0 with 18 sightings: the drone hovered at the start of the
   search and re-observed the same spot from the same pose.
3. Two extra candidates 5–6 m from the true target (likely duplicates) — they cost an
   inspection each if the agent is careful.
4. The close-up from the 8 m altitude floor shows the backpack at ~55 px; enough to tell
   the deep-red JanSport (target) from the lighter multi-pocket backpack (distractor), but
   barely.
5. Distinguishing two red backpacks needed two inspections (≈45 s each).

Fix applied (v0.1): one observation per candidate per frame (blobs within the merge radius
in one frame collapse to the strongest), coverage counted with the same footprint as
proposals; every detection is logged with its pose (`detections.jsonl`) and all candidates
are dumped (`candidates.json`) for offline diagnosis.

---

## v0.2 — "real-life" simulation (requested: behave like the real drone so the agent succeeds first time)

The ideal simulator was flattering us in ways a real drone never would. Changes, all on by
default for every eval (`scenarios/generate.py --ideal` turns them off for debugging):

| real-world effect | how it is simulated |
|---|---|
| state estimate | **SITL defaulted to `AHRS_EKF_TYPE 10` = simulator ground truth.** Now EKF3 fusing IMU/GPS/baro/compass |
| GPS error | white noise (`SIM_GPS1_NOISE`) + a slowly wandering 0.8–2 m bias (`sim_gps_drift.lua`, mean-reverting random walk on the glitch offsets) |
| baro | `SIM_BARO_RND` noise |
| wind | Gazebo `WindEffects` on the airframe (SITL's `SIM_WIND_*` is ignored by the JSON backend): breeze 0.5–3 m/s on every tier, 4–8 m/s gusty on hard; also adds air drag, so the drone now pitches ~10° at 6 m/s like a real quad |
| lens | radial distortion (k1 −0.06, k2 0.008); the server undistorts with a *measured* calibration (`sim/camera_calibration.json`, deliberately ≈0.4% off) instead of the simulator's intrinsics |
| video link | motion blur from speed × exposure, auto-exposure drift, vignetting, sensor noise, JPEG q55–85 |
| timing | frames arrive 0.17–0.23 s late (+jitter), 2–10% dropped, stamped on *arrival* (as on a companion computer) |
| light | random sun elevation/azimuth/intensity per scenario |

### What realism broke, and the fixes (calibration flight, steady flight, 25 m, 6 m/s)

| step | median error | note |
|---|---|---|
| ideal sim, ground-truth pose | 0.22 m | v0 |
| + camera realism, offset −0.20 s (nominal latency) | 0.96 m | timing residual 0.17 s: effective pipeline latency is 0.37 s |
| + measured offset −0.37 s | 0.38 m | residual 0.02 s |
| + EKF3 + drag/wind | **5.96 m** | errors grow with body pitch |
| + full camera attitude (body ⊗ gimbal) | 1.26 m (p90 2.3 m) | residual timing 0.001 s; remaining error ≈ GPS/EKF bias |

* The 5.96 m regression: ArduPilot reports a servo gimbal's attitude **relative to the
  airframe** (it reported −65° while the body pitched −25° and the camera, verified in
  Gazebo, stayed within 0.5° of nadir). The projection took it as earth-frame. With a
  ground-truth pose and no drag the airframe cruised level, so the bug was invisible.
  Fix: camera attitude = EKF body attitude ⊗ body-relative gimbal quaternion.
* Timing offset separated from GPS bias by flying opposite headings: bias flips sign with
  heading, latency does not.
* What is left (~1–2 m) is the GPS/EKF absolute error every non-RTK drone has; it goes
  straight into reported positions. On hardware: RTK or a ground control point would
  remove it.

---

## v1 — baseline under real-world conditions (stopped after 2 runs)

| run | target | result | note |
|---|---|---|---|
| easy-2000 | – | success, 3.54 m, 0 FP, 7 calls | |
| medium-2001 | person (white t-shirt) | **miss**, 0 reports, 11 calls | target never became a candidate |

Stopped early on purpose: each eval run starts a fresh server from the working tree, so
fixing code mid-eval would mix versions. Evals now run from a frozen git-worktree snapshot
(`scripts/eval_snapshot.sh`).

Diagnosis of medium-2001 (replaying the saved frames, `eval/vision_bench.py`): the person
is clearly visible, contrast 73 vs threshold 18, yet **zero proposals**. Two compounding
causes, both invisible in the ideal sim:
1. With a random low sun the person's cast shadow glued onto the blob, and
2. off nadir a *standing* person is seen partly from the side (head to feet): the image
   footprint was 1.75 m against an assumed 0.6 m "size from above" and a 1.5 m cap.

The agent's own note: "thumbnails too dark and small to judge; every close-up came back
with redetected_up_close false" — it correctly reported nothing rather than guessing.

## v2 — shadows, tall objects, legible images

* Shadow suppression in proposals: pixels darker than the local background (<0.8×) with
  the same normalised-RGB chromaticity are removed from the blob mask (Lab chroma is not
  brightness-invariant; a darkened green shifts a/b by ~20).
* Height-aware size prior: each object type has footprint + height; the expected blob size
  per detection is `footprint + height × (ground offset / altitude)`. Proposal size window
  widened to max(3 m, 4× footprint); the scorer's size prior does the discrimination.
* Thumbnails and close-ups shown to the LLM are contrast-stretched (vision still sees raw).

On the medium-2001 frame: person proposal recovered (text cue 0.83), size factor 0.31 → 0.88.

### v2 run easy-3003: GPS drift between search and inspection (fixed for v3)

Success, but 4.3 m error and 13 tool calls. All 14 search sightings were consistently
~4.7 m off (the GPS bias at the time). By the time of the inspection the bias had
wandered, so the backpack was in the 8 m close-up frame but outside the 3 m radius the
inspector looked in; the close-up was a centre crop of grass. The agent fell back to
manual goto + capture_image and noted it could only report the candidate's coordinates.
A real drone does exactly this.

v3 inspection: re-acquire visually across the whole frame at each descent step,
weighting detections by score × closeness on a GPS-drift scale (6 m), re-centre, and crop
the close-up from detections in the *final* frame (it used boxes from an earlier, higher
frame). If nothing is re-detected the agent gets the full frame too, plus
`object_in_closeup: false`. Test: `tests/test_inspect_reacquire.py` (candidate 4 m off →
re-centred within 1 m).

### v2 run hard-3005: false report — caused by the simulator, not the agent

Target: blue hatchback, occluded under a tree. The agent reported "c6", a blue hatchback,
with confidence 0.55 and a note that c5 looked identical. Ground truth said c6 was the
*white* car. Both close-ups do show blue hatchbacks: **all three Fuel hatchbacks declare a
material named `Hatchback` with texture `hatchback.png`, and Ogre caches materials by name,
so in a scene with several of them every car rendered blue.** Single-object reference
renders never showed it. Every scenario with a red/white hatchback distractor was unfair
until now. Fix: asset build prefixes every material and texture with the model slug
(verified: white, red and blue render side by side). Note: the running v2 eval shares the
generated assets, so v2 runs 7+ have the fix, runs 1–6 did not.

Second problem in the same run: the reference photo's top border is sky. The single-median
background picked the sky strip as the "object", CLIP labelled it "grey person", and the
agent was shown that crop as the reference ("I couldn't view the reference image myself").
Fixes: background = k-means clusters of border colours (a pixel is foreground only if far
from all of them); regions spanning the image edge to edge are rejected; reference renders
aim at the object's mid-height so tall objects (people) are not cut off.

Open: the occluded target never became a candidate (to diagnose from the saved frames).

### v2 run medium-3007: false report between two red backpacks (fixed for v3)

The target (JanSport, deep red, black back panel) was candidate c2 and was inspected, but
the close-up showed it from straight above at ~45 px: "a plain red block". The agent
dismissed it, re-searched, and reported the look-alike red backpack, which it saw only
partly, at the edge of its close-up (the old crop bug).

v3:
* **Zoom camera.** Real search drones carry zoom cameras; the simulated gimbal camera now
  keeps ardupilot_gazebo's CameraZoomPlugin (up to 6× optical relative to the 1.2 rad
  lens), driven through the frame bridge like a camera control API; each frame reports
  its zoom and the server scales the intrinsics. Inspection stays at 12 m (above trees and
  roofs) and zooms until the object spans ~220 px, re-centring halfway.
* **Close-up beside the reference** in every inspection image, so look-alikes are judged
  side by side.
* **One-shot flow:** `execute_search(plan_id, inspect_top=N)` inspects the N best
  candidates on a nearest-first route and returns all close-ups in one response; the
  agent only has to compare and report. Tested end-to-end on the fake backend.

## v2 final results (18 flown runs, 3 lost to a render-harness bug)

| tier | runs | success | median err | max err | false reports / 20 | median time | median battery | median calls |
|---|---|---|---|---|---|---|---|---|
| all | 18 | 77.8% | 1.85 m | 4.5 m | 3.3 | 359 s | 26.5% | 8 |
| easy | 7 | 85.7% | 1.93 m | 4.3 m | 0 | 298 s | 21% | 8 |
| medium | 6 | 83.3% | 1.5 m | 2.29 m | 3.3 | 384 s | 26.5% | 8 |
| hard | 5 | 60% | 3.27 m | 4.5 m | 8.0 | 386 s | 32% | 8 |

Target in the candidate list: 94% of runs. Failures: hard-3005 (identical-looking cars:
material-cache bug), medium-3007 and hard-3008 (red backpack look-alike, 45 px close-ups,
inspection crop/position bugs), easy-3018 (no frame at inspection, grass close-ups).

## Self-play session 2 (v3 code, medium-4242, blue car) — three more simulator bugs

Flown by hand with `execute_search(inspect_top=3)`. Candidate positions in the 40 m search
were 12–24 m off, and the target and a white car each appeared as several candidates.
Chasing it with a live diagnostic (camera pose from Gazebo vs projection) found:

1. **Camera frames backed up.** The camera-realism step (distortion, blur, noise, JPEG in
   pure numpy) took >200 ms per 1280×960 frame against a 200 ms camera period. Frames
   queued in the bridge, latency grew without bound over a mission (frames >10 s late)
   and were stamped with their processing time, so each was paired with the wrong pose.
   Short calibration flights hid it (the 0.37 s "measured latency" was partly this
   backlog). Fixes: OpenCV implementation (220 → 35 ms), stale frames are dropped like
   on a real link, frames are stamped capture + modelled latency, and the server rejects
   frames older than the telemetry. Re-measured offset: −0.255 s.
2. **The zoom plugin reset the lens.** ardupilot_gazebo's CameraZoomPlugin slews to its own
   hard-coded 2.0 rad FOV on load: the 1.2 rad camera silently became 0.35× focal length
   (a 10 m offset showed as 131 px instead of 374). The bridge now pins zoom 1 at
   start-up; gz's camera_info does not follow the plugin, so the bridge reports the
   commanded zoom.
3. **Gimbal attitude model.** Composing the EKF attitude with ArduPilot's reported gimbal
   quaternion leaked airframe roll into the projection (up to 15 m during banked turns,
   3.6 m from 4.9° of wind roll at 40 m): at −90° pitch the quaternion is built from
   degenerate Euler angles and cannot carry roll. The message flags say roll and pitch are
   earth-locked, so the camera attitude is the commanded earth-frame target (roll 0,
   pitch −90) plus vehicle yaw. Same flights, steady frames: earth-locked 2.14 m median
   (p90 3.3) vs composition 2.40 m (p90 3.8); this run's GPS bias alone was ~2 m.

Also: EKF3 can take >90 s to converge from a cold start under load; arming waits 180 s.
