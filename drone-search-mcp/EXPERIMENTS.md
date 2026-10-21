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

### v3 run easy-5000: success (1.74 m, of which 0.99 m GPS bias) but 753 s — fixes for v4

* The search took 455 s for a 100 m square: the drone averaged 2.9 m/s. The speed governor
  ("each spot analysed in ≥2 frames") measured the vision interval in wall-clock time while
  the drone flies in sim time; the simulator ran at ~0.3× real time, so it throttled a
  drone whose vision was keeping up (0.7 sim-s per frame). Now measured from frame stamps.
* Proposals capped at 24 per frame (the wider size window + shadow fragments had raised
  CLIP load, slowing the whole simulation).
* Zoomed close-ups: the background kernel (a few metres on the ground) became larger than
  the frame at zoom ×4 and swallowed the object ("object_in_closeup: false" while the
  image showed it). Kernel capped at half the frame; the object is now proposed.
* Agent note: it did not use `inspect_top`; the eval system prompt predates it.

## v3 / v4 status and an environment problem

v3 (commit 4946d17) ran 2 runs before being stopped for the v4 speed fix: both successes
(easy-5000 1.74 m, 7 calls; medium-5001 1.77 m, 6 calls — the red-backpack look-alike case
solved in one shot with `inspect_top`), but 753 s and 964 s to find.

Simulator fixes found while starting v4:
* **CameraZoomPlugin removed.** It slews toward a hard-coded 2.0 rad FOV from load and its
  focal-length bookkeeping never converges, so it re-configures the camera on every
  physics step (real-time factor fell to ~0.3 in v3, later ~0.04). Replaced by a
  dual-sensor gimbal: a second, fixed 4× telephoto camera on the same gimbal (as on real
  search payloads); gz-sensors only renders subscribed cameras, so the bridge switches
  subscriptions on a zoom request and the idle sensor costs nothing. Frames report
  zoom 4.0 when taken with it; verified switching wide → tele → wide.
* **Teardown escalates to SIGKILL** and waits until no Gazebo/bridge/SITL is left (a Gazebo
  that ignored SIGTERM kept the JSON port, and every later SITL waited for physics forever).

**Environment:** in the last hours of this session the cloud VM's memory became pathologically
slow for fresh allocations (guest metrics normal, 14 GB available, no pressure): touching
new memory runs at ~20 MB/s, a CLIP forward pass went from 0.32 s to 24.5 s, and even
ardupilot_gazebo's stock `iris_runway` world can no longer keep SITL in lockstep. Dropping
caches and deleting artifacts did not help; it is below the guest. v4 could not be run
here and needs a fresh machine.

## v4 (commit c4e73ee) — running on a fresh machine

Run easy-6000 (person): success, 1.82 m of which **0.12 m** without the GPS bias, found in
194 s (v3: 753 s — the sim-time speed governor works). Fixes queued for v5 from this run:
* The first plan/execute failed with "home position unknown": ArduPilot sets home only once
  EKF3 has a GPS origin. The geofence check now waits up to 30 s for home (still failing
  closed after that).
* "object_in_closeup: false" while the close-up clearly showed the person: CLIP gives a
  zoomed top-down person a weak text cue (0.12; score 0.39). The final close-up check runs
  with a lower threshold near the re-acquired position, since the drone is hovering on it.

Run hard-6002: **never flew** — EKF3 stayed unconverged and home unset for the whole
session. The simulated GPS bias random walk stepped every 0.2 s, so a parked receiver
appeared to move at ~0.3 m/s and EKF3's pre-arm GPS checks never passed. Fixes for v5:
the bias is now low-passed over 10 s (still 1–2 m, wandering over minutes, like a real
receiver); `state.waiting_for` tells the agent what the vehicle still needs before it can
fly; `plan_search` waits for a `set_search_target` issued in parallel instead of failing
(agents keep doing this).

## v5 (commit 5542f8b) — 21 new random scenarios, 7 per tier

| tier | runs | success | median error | max error | false reports / 20 | median time | median calls |
|---|---|---|---|---|---|---|---|
| all | 21 | 76.2% | 2.03 m | 3.26 m | 2.86 | 252 s | 5 |
| easy | 7 | 100% | 1.77 m | 2.96 m | 0 | 208 s | 5 |
| medium | 7 | 100% | 2.49 m | 3.26 m | 0 | 290 s | 5 |
| hard | 7 | 28.6% | 0.69 m | 1.26 m | 8.57 | 377 s | 5 |

Every scored error is under 5 m; with the true injected GPS bias removed the median is
**0.38 m**, so the remaining error is the drone's own GPS. Easy and medium are solved
(14/14, no false reports, ~5 tool calls). All five failures are hard-tier objects under
trees; three of them ended in a false report. Each failure was traced from its trace page
(`eval/trace_report.py`) and saved frames:

| run | what happened | root cause | fix (commit) |
|---|---|---|---|
| hard-7002 | occluded white box never became a candidate; agent reported nothing | detection under canopy | open |
| hard-7005 | target was candidate c4 and was inspected, but the 4× close-up (~4 m across) showed only tree shade; agent rejected it | narrow telephoto view + drift | fall back to the wide camera when the tele frame shows nothing (e215fea) |
| hard-7008 | false report: person in a blue shirt for one in a white t-shirt | inspection asked for 1.8× zoom, below the wide/tele 2× switch, so the close-up stayed wide | zoom as far as keeps the object in half the frame; prompt to check colours vs look-alikes (b1dc968) |
| hard-7011 | false report: beige box for the white box; every close-up said `object_in_closeup: false` | ArduPilot turned to face each short re-centring move (~45°/s); the analyzer skips rotating frames | hold heading on inspection moves, wait for a steady frame (8a0e16a) |
| hard-7017 | false report: beige box again; real box was candidate 9 of 10, not inspected | beige vs white is not visible by eye in a dim close-up | measured `colour_check` (CIELAB tint vs reference; white 1.4–2.2, beige 8.1–10.0 on all 41 v5 close-ups) (c923cf0) |

Agent-reported confusion also exposed unlabelled images (thumbnails and close-ups arrive as
an unnumbered list) and a contradictory close-up note; every image now carries its
candidate id and responses list their images in order (0b49e37). The
`object_in_closeup: false` complaints in easy/medium runs are the same heading bug.

Every v5 run has a trace page and a flight video (`output/traces/`, `output/videos/`).

## v6 (commit d95486a) — the v5 fixes, 21 new scenarios

| tier | runs | success | median error | max error | false reports / 20 | median time | median calls |
|---|---|---|---|---|---|---|---|
| all | 21 | 81.0% | 1.75 m | 3.54 m | 2.86 | 283 s | 5 |
| easy | 7 | 100% | 1.72 m | 2.84 m | 0 | 199 s | 5 |
| medium | 7 | 100% | 1.91 m | 3.54 m | 0 | 301 s | 5 |
| hard | 7 | 42.9% | 1.32 m | 2.15 m | 8.57 | 373 s | 6 |

Median error without the true GPS bias: 0.56 m. The target became a candidate in 95% of
runs (v5: 86%). The v5 fixes worked as intended in flight: close-ups were steady and
labelled, `object_in_closeup` agreed with the images, and no white-vs-beige mistake recurred.
(The run was restarted once after its first two runs, to replace a colour check that read
a red backpack's reference as black; a container restart later interrupted it once and it
resumed from its results file.)

Failures (all hard tier, all objects under or near trees):

| run | what happened | fix (commit) |
|---|---|---|
| hard-8002 | blue car under cover never became a candidate; agent correctly reported nothing. The colour check called two white cars "same colours" as the blue reference (it matched the reference's grey windows) | the reference's saturated colour must appear in the close-up (281bdf8) |
| hard-8011 | false report: a second red backpack; all three close-ups matched the reference's colours and the target (ranked 7th) was never inspected | `lookalikes` note naming matching close-ups and uninspected strong candidates (666805f) |
| hard-8014 | false report: the decoy backpack; the target was inspected but straight down showed only canopy, and the decoy's colour was measured on sunlit grass | attach the search-time view when the close-up's colours do not match but the search view's do; ignore sunlit/shaded ground in colour measurement (9c53ff6) |
| hard-8020 | false report: the decoy backpack again; target (a "small red spot under trees", ranked 4th) not inspected | covered by the `lookalikes` note (it would have listed the target) |

Efficiency: hard-8008 succeeded but re-flew the whole search to see candidates beyond the
first six (10 calls, 528 s) → `list_candidates` pages through them without flying (49990e5).
Agent-reported confusion also led to `not_seen_in_closeup` (faint reference colours, e.g.
jeans from above, that the close-up does not show; 6e5d22d).

Every v6 run has a trace page and a flight video (`output/traces/`, `output/videos/`).

## v7 (commit 5ac9c27) — targets met

| tier | runs | success | median error | max error | false reports / 20 | median time | median calls |
|---|---|---|---|---|---|---|---|
| all | 21 | **85.7%** | 1.71 m | **4.15 m** | **0.95** | 288 s | 5 |
| easy | 7 | 100% | 1.74 m | 4.15 m | 0 | 190 s | 5 |
| medium | 7 | 100% | 2.06 m | 4.02 m | 0 | 305 s | 5 |
| hard | 7 | 57.1% | 1.12 m | 1.44 m | 2.86 | 359 s | 6 |

All three targets hold on fresh scenarios: success ≥ 85%, every error < 5 m, fewer than 2
false reports per 20. Median error without the true GPS bias: 0.40 m; the two errors above
4 m were 2.8 m and 4.0 m of simulated GPS bias. (The run was restarted once after three
runs to replace a colour check that called a red close-up "red missing" against a red
reference.) The look-alike warning, `list_candidates` and the colour fixes were used as
intended in flight; the red-backpack decoy that caused every v6 false report was resolved
correctly in hard-9011.

Failures (hard tier, all objects under trees):

| run | what happened | fix (commit) |
|---|---|---|
| hard-9002 | false report: the decoy red backpack. The look-alike warning fired and the agent inspected more, but the real backpack never became a candidate | close-ups cropped so the object fills half the image, for finer detail (9bc5fcc); detection under canopy remains open |
| hard-9014 | no report: the person under a tree was inspected, but the close-up was nothing but canopy, so no colour could be measured and the search-view fallback did not fire | the search view is also attached when the close-up has no measurable object (85e2bbc) |
| hard-9017 | no report: same case as hard-9014 | same fix |

Agent-reported confusion in easy-9018 led to the verdict naming faint unseen colours
itself ("same colours as the reference, apart from the blue not visible in the close-up",
c70e10a).

Every v7 run has a trace page and a flight video (`output/traces/`, `output/videos/`).
