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
