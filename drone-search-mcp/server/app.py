"""drone-search-mcp: an MCP server that finds an object from the air.

The LLM plans (where to search, which candidate to inspect, whether the close-up really is
the target); code flies (coverage patterns, detection on every frame, deduplication,
visual re-centring). Tools are deliberately high-level: there are no stick inputs.

Run:  python -m server [--allow-actuation] [--backend sitl|fake]
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Annotated, Any, Literal

import cv2
import numpy as np
import structlog
from fastmcp import FastMCP
from fastmcp.utilities.types import Image as McpImage
from PIL import Image
from pydantic import Field

from backends.base import DroneBackend
from common.geo import distance_m
from server.errors import (
    Aborted,
    DroneSearchError,
    InvalidArgument,
    NotFound,
    StateConflict,
    VehicleError,
)
from server.mission import MissionRunner
from server.planner import EnergyModel, SearchPlan, circle_polygon, make_plan
from server.recorder import FlightRecorder
from server.safety import SafetyConfig, SafetyGate
from vision.matcher import TargetSpec, build_target
from vision.pipeline import AnalyzerConfig, Candidate, CandidateTracker, FrameAnalyzer

log = structlog.get_logger(__name__)

INSTRUCTIONS = """\
Find an object from the air with a simulated drone, then report its GPS position with a photo.

Typical flow:
1. get_status - check the drone is ready (battery, GPS, safety).
2. set_search_target - give the reference image and/or a text description.
3. plan_search - give the search area; the server picks an altitude from the target size
   and returns path length, time and battery estimates. Re-plan if it does not fit.
4. execute_search - flies the whole pattern autonomously and returns ranked candidates
   with thumbnails. Vision runs on every frame in code; you do not need to look at frames.
5. inspect_candidate - for the best candidates, fly over and descend for a close-up.
   Look at the close-up yourself and decide whether it is the target.
6. report_finding - report the confirmed candidate (once per target), then return_home.

Every tool response ends with `state`, read from live telemetry after the action.
Errors carry `code`, `message` and `next_step`. emergency_stop works at any time.
"""


def _configure_logging(level: str) -> None:
    # stdout is the MCP stdio channel: logs must go to stderr
    logging.basicConfig(stream=sys.stderr, level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
    )


def _jpeg(img: np.ndarray, max_side: int, quality: int = 85) -> McpImage:
    h, w = img.shape[:2]
    s = min(1.0, max_side / max(h, w))
    if s < 1:
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="JPEG", quality=quality)
    return McpImage(data=buf.getvalue(), format="jpeg")


class DroneSearchServer:
    def __init__(self, backend: DroneBackend, safety_cfg: SafetyConfig, out_dir: Path, record: bool = True) -> None:
        self.backend = backend
        self.out_dir = out_dir
        self.safety = SafetyGate(safety_cfg, backend)
        self.energy = EnergyModel()
        self.recorder = FlightRecorder(backend, out_dir, context=self._recording_context, enabled=record)
        self.runner = MissionRunner(backend, self.recorder, self.energy)
        self.safety.on_reserve(lambda: self.runner.request_abort("battery reserve reached"))
        self.target: TargetSpec | None = None
        self.target_info: dict[str, Any] = {}
        self.plans: dict[str, SearchPlan] = {}
        self.tracker = CandidateTracker()
        self.analyzer_cfg = AnalyzerConfig()
        self.findings: list[dict[str, Any]] = []
        self.last_search: dict[str, Any] | None = None
        self.tool_calls = 0
        self._connected = False
        self._connect_lock = threading.Lock()
        self.eval_dir = Path(os.environ.get("DSM_EVAL_DIR", Path.home() / ".drone_search_eval")).resolve()

    # ------------------------------------------------------------- plumbing
    def ensure_connected(self) -> None:
        with self._connect_lock:
            if self._connected:
                return
            self.backend.connect()
            # SITL proves itself with SIMSTATE at 1 Hz; give it a moment before we judge
            t0 = time.time()
            while time.time() - t0 < 10 and not self.backend.is_simulation():
                time.sleep(0.2)
            self.safety.start_monitor()
            self._connected = True
            self.out_dir.mkdir(parents=True, exist_ok=True)
            log.info("server.connected", simulation=self.backend.is_simulation(), out_dir=str(self.out_dir))

    def state(self) -> dict[str, Any]:
        t = self.backend.telemetry()
        dist_home = None
        if t.lat is not None and t.home_lat is not None:
            dist_home = round(distance_m(t.home_lat, t.home_lon, t.lat, t.lon), 1)  # type: ignore[arg-type]
        return {
            "lat": None if t.lat is None else round(t.lat, 7),
            "lon": None if t.lon is None else round(t.lon, 7),
            "alt_m": None if t.alt_rel_m is None else round(t.alt_rel_m, 1),
            "heading_deg": None if t.heading_deg is None else round(t.heading_deg),
            "groundspeed_ms": round(t.groundspeed_ms, 1),
            "distance_from_home_m": dist_home,
            "mode": t.mode,
            "armed": t.armed,
            "battery_pct": None if t.battery_pct is None else round(t.battery_pct, 1),
            "gps_fix": t.gps_fix,
            "ekf_ok": t.ekf_ok,
            "busy_with": self.runner.active,
            "battery_reserve_triggered": self.safety.state.reserve_triggered,
        }

    def respond(self, payload: dict[str, Any], images: list[McpImage] | None = None) -> Any:
        payload["state"] = self.state()
        text = json.dumps(payload, default=_json_default, indent=1)
        return [text, *images] if images else text

    def call(self, name: str, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Top-level wrapper for every tool: logging, connection, structured errors."""
        self.tool_calls += 1
        t0 = time.time()
        log.info("tool.call.start", tool=name)
        try:
            self.ensure_connected()
            out = fn(*args, **kwargs)
            log.info("tool.call.complete", tool=name, seconds=round(time.time() - t0, 2))
            return out
        except DroneSearchError as exc:
            log.warning("tool.call.refused", tool=name, code=exc.code, error=exc.message)
            return self._error(exc)
        except Exception as exc:
            log.error("tool.call.error", tool=name, exc_info=True)
            return self._error(DroneSearchError(f"{type(exc).__name__}: {exc}"))

    def _error(self, exc: DroneSearchError) -> str:
        body = exc.to_dict()
        try:
            body["state"] = self.state()
        except Exception:
            log.error("tool.state_unavailable", exc_info=True)
        return json.dumps(body, default=_json_default, indent=1)

    def _recording_context(self) -> dict[str, Any]:
        last = max(self.plans.values(), key=lambda p: p.id, default=None) if self.plans else None
        return {
            "plan": None
            if last is None
            else {"waypoints": last.waypoints, "area": last.area_polygon, "altitude_m": last.altitude_m},
            "plans": {pid: {"waypoints": p.waypoints, "area": p.area_polygon} for pid, p in self.plans.items()},
            "candidates": [
                {"id": c.id, "lat": c.lat, "lon": c.lon, "confidence": c.confidence, "status": c.status}
                for c in self.tracker.ranked()
            ],
            "home": [self.backend.telemetry().home_lat, self.backend.telemetry().home_lon],
            "target": self.target_info.get("label_used_for_matching"),
            "findings": self.findings,
        }

    def _candidate_dict(self, c: Candidate) -> dict[str, Any]:
        t = self.backend.telemetry()
        cues = c.best_cues
        return {
            "candidate_id": c.id,
            "lat": round(c.lat, 7),
            "lon": round(c.lon, 7),
            "confidence": round(c.confidence, 3),
            "best_frame_score": round(c.best_score, 3),
            "cues": {"text": _r(cues.text), "image": _r(cues.image), "color": _r(cues.color), "size": _r(cues.size)},
            "times_seen": c.n_obs,
            "frames_covering_spot": c.n_frames_covered,
            "position_spread_m": None if c.n_obs < 2 else round(c.position_spread_m, 1),
            "est_size_m": round(c.size_m, 2),
            "distance_from_home_m": None
            if t.home_lat is None
            else round(distance_m(t.home_lat, t.home_lon, c.lat, c.lon), 1),  # type: ignore[arg-type]
            "status": c.status,
        }

    def _thumb(self, c: Candidate) -> McpImage:
        return _jpeg(c.best_crop, 160, 80)

    # ----------------------------------------------------------------- tools
    def get_status(self) -> Any:
        return self.respond(
            {
                "safety": self.safety.describe(),
                "search_target": self.target_info or None,
                "plans": [p.summary() for p in self.plans.values()],
                "mission_progress": self.runner.progress or None,
                "candidates": [self._candidate_dict(c) for c in self.tracker.ranked()[:5]],
                "findings": self.findings,
                "energy_model_pct_per_min": round(self.energy.pct_per_min_cruise, 2),
                "status_text": self.backend.telemetry().status_text[-3:],
            }
        )

    def set_search_target(self, image_path: str | None, text: str | None, object_size_m: float | None) -> Any:
        if not image_path and not text:
            raise InvalidArgument("give image_path, text, or both")
        ref = None
        if image_path:
            p = Path(image_path).expanduser().resolve()
            if p == self.eval_dir or self.eval_dir in p.parents:
                raise InvalidArgument(
                    "that path is in the evaluation ground-truth directory, which this server may not read",
                    next_step="Pass the mission's reference image.",
                )
            if not p.is_file():
                raise InvalidArgument(f"no such image file: {p}")
            try:
                ref = np.asarray(Image.open(p).convert("RGB"))
            except OSError as exc:
                raise InvalidArgument(f"cannot read image {p}: {exc}") from exc
        if object_size_m is not None and not 0.05 <= object_size_m <= 30:
            raise InvalidArgument("object_size_m must be between 0.05 and 30 metres")
        self.target = build_target(text, ref, object_size_m)
        self.tracker = CandidateTracker(merge_radius_m=max(3.0, self.target.size_m * 0.75))
        self.target_info = {
            "text": text,
            "reference_image": image_path,
            "label_used_for_matching": self.target.label,
            "label_inferred_from_image": self.target.inferred_label,
            "assumed_object_size_m": self.target.size_m,
        }
        hint = None
        if image_path and not text:
            hint = (
                f"The image was read as '{self.target.inferred_label}'. If that is wrong, call "
                "set_search_target again with a text description as well."
            )
        imgs = [_jpeg(self.target.ref_crop, 256)] if self.target.ref_crop is not None else None
        return self.respond(
            {"search_target": self.target_info, "hint": hint, "note": "Previous candidates were cleared."}, imgs
        )

    def plan_search(
        self,
        area_polygon: list[list[float]] | None,
        center_lat: float | None,
        center_lon: float | None,
        radius_m: float | None,
        altitude_m: float | None,
        overlap: float,
        pattern: str,
        speed_ms: float,
    ) -> Any:
        if area_polygon:
            if len(area_polygon) < 3 or any(len(p) != 2 for p in area_polygon):
                raise InvalidArgument("area_polygon needs at least 3 [lat, lon] pairs")
            poly = [(float(a), float(b)) for a, b in area_polygon]
        elif center_lat is not None and center_lon is not None and radius_m:
            if not 5 <= radius_m <= self.safety.cfg.max_radius_m:
                raise InvalidArgument(f"radius_m must be between 5 and {self.safety.cfg.max_radius_m:.0f}")
            poly = circle_polygon(center_lat, center_lon, radius_m)
        else:
            raise InvalidArgument("give area_polygon, or center_lat + center_lon + radius_m")
        if not 0 <= overlap <= 0.8:
            raise InvalidArgument("overlap must be between 0 and 0.8 (fraction of the camera footprint)")
        if not 1 <= speed_ms <= self.safety.cfg.max_speed_ms:
            raise InvalidArgument(f"speed_ms must be between 1 and {self.safety.cfg.max_speed_ms:g}")
        if altitude_m is not None:
            self.safety.check_point(poly[0][0], poly[0][1], altitude_m, "plan altitude")
        frame = self.backend.latest_frame(max_age_s=30)
        if frame is None:
            raise VehicleError("no camera frame yet, cannot size the pattern (is the camera running?)")
        t = self.backend.telemetry()
        if t.lat is None or t.lon is None:
            raise VehicleError("no GPS position yet")
        home = (t.home_lat or t.lat, t.home_lon or t.lon)
        plan = make_plan(
            poly,
            frame.camera,
            self.target.size_m if self.target else None,
            altitude_m,
            overlap,
            pattern,
            speed_ms,
            (t.lat, t.lon),
            home,
            self.energy,
            alt_limits=(max(15.0, self.safety.cfg.min_alt_m), min(40.0, self.safety.cfg.max_alt_m)),
        )
        feasible, problems = True, []
        for la, lo in plan.waypoints:
            try:
                self.safety.check_point(la, lo, plan.altitude_m, "waypoint")
            except DroneSearchError as exc:
                feasible = False
                problems.append(exc.message)
                break
        try:
            self.safety.check_battery_for(plan.est_battery_pct)
        except DroneSearchError as exc:
            feasible = False
            problems.append(exc.message)
        self.plans[plan.id] = plan
        return self.respond(
            {
                "plan": plan.summary(),
                "feasible": feasible,
                "problems": problems,
                "next_step": "execute_search(plan_id)"
                if feasible
                else "Adjust the area, altitude or overlap and plan again.",
            }
        )

    def execute_search(self, plan_id: str, max_candidates: int) -> Any:
        self.safety.require_actuation()
        plan = self.plans.get(plan_id)
        if plan is None:
            raise NotFound(
                f"no plan {plan_id!r}", next_step=f"Known plans: {sorted(self.plans)}. Call plan_search first."
            )
        if self.target is None:
            raise StateConflict("no search target set", next_step="Call set_search_target first.")
        if self.safety.state.reserve_triggered:
            raise StateConflict("battery reserve was reached; the drone is returning home")
        for la, lo in plan.waypoints:
            self.safety.check_point(la, lo, plan.altitude_m, "waypoint")
        self.safety.check_battery_for(plan.est_battery_pct)
        self.runner.begin("execute_search")
        try:
            analyzer = FrameAnalyzer(self.target, self.analyzer_cfg)
            report = self.runner.run_search(plan, analyzer, self.tracker)
        finally:
            self.runner.end()
        top = [c for c in report.candidates if c.status != "rejected"][:max_candidates]
        self.last_search = {"plan_id": plan_id, "completed": report.completed}
        payload = {
            "plan_id": plan_id,
            "completed": report.completed,
            "abort_reason": report.abort_reason,
            "duration_s": round(report.duration_s),
            "frames_analyzed": report.frames_analyzed,
            "distance_flown_m": round(report.distance_flown_m),
            "area_coverage_pct": round(report.coverage_pct),
            "battery_used_pct": None
            if report.battery_start_pct is None or report.battery_end_pct is None
            else round(report.battery_start_pct - report.battery_end_pct, 1),
            "n_candidates_total": len(report.candidates),
            "candidates": [self._candidate_dict(c) for c in top],
            "how_to_read": "confidence fuses detection score, repeat sightings and size. Thumbnails "
            "follow in the same order. Inspect the strongest before reporting.",
        }
        if not top:
            payload["next_step"] = (
                "No candidates. Consider a lower altitude (larger target in pixels), more overlap, or a different area."
            )
        return self.respond(payload, [self._thumb(c) for c in top])

    def inspect_candidate(self, candidate_id: str, altitude_m: float | None) -> Any:
        self.safety.require_actuation()
        if self.target is None:
            raise StateConflict("no search target set", next_step="Call set_search_target first.")
        c = self.tracker.get(candidate_id)
        if c is None:
            raise NotFound(
                f"no candidate {candidate_id!r}",
                next_step=f"Known candidates: {[x.id for x in self.tracker.ranked()][:10]}",
            )
        frame = self.backend.latest_frame(max_age_s=30)
        if frame is None:
            raise VehicleError("no camera frame")
        if altitude_m is None:
            # fill ~120 px with the object, but stay above trees and the altitude floor
            altitude_m = float(np.clip(c.size_m * frame.camera.fx / 120, self.safety.cfg.min_alt_m, 20))
        search_alt = max(
            self.plans[self.last_search["plan_id"]].altitude_m if self.last_search else 20.0, self.safety.cfg.min_alt_m
        )
        self.safety.check_point(c.lat, c.lon, altitude_m, "inspection point")
        self.safety.check_point(c.lat, c.lon, search_alt, "transit")
        self.runner.begin("inspect_candidate")
        try:
            res = self.runner.run_inspect(
                c, FrameAnalyzer(self.target, self.analyzer_cfg), search_alt, altitude_m, self.out_dir / "closeups"
            )
        finally:
            self.runner.end()
        c.inspected, c.status = True, "inspected"
        c.lat, c.lon = res["lat"], res["lon"]
        c.closeup_path, c.closeup_score = res["closeup_path"], res["closeup_score"]
        cues = res["cues"]
        payload = {
            "candidate_id": c.id,
            "lat": round(res["lat"], 7),
            "lon": round(res["lon"], 7),
            "inspection_alt_m": None if res["alt_m"] is None else round(res["alt_m"], 1),
            "redetected_up_close": res["redetected"],
            "closeup_score": _r(res["closeup_score"]),
            "closeup_cues": None
            if cues is None
            else {"text": _r(cues.text), "image": _r(cues.image), "color": _r(cues.color)},
            "position_refined_by_m": round(res["refined_shift_m"], 1),
            "closeup_image_path": res["closeup_path"],
            "question_for_you": (
                f"Does the close-up show {self.target.label}? If yes, call report_finding("
                f"'{c.id}', confidence, notes). If not, inspect the next candidate."
            ),
        }
        return self.respond(payload, [_jpeg(res["closeup"], 512, 90)])

    def capture_image(self) -> Any:
        f = self.backend.latest_frame(max_age_s=5)
        if f is None:
            raise VehicleError("no fresh camera frame")
        return self.respond(
            {
                "frame_seq": f.seq,
                "camera_alt_m": f.pose.alt_rel_m,
                "gimbal_pitch_deg": f.pose.gimbal_pitch_deg,
                "note": "Image top is the drone's heading; the frame is a downward view.",
            },
            [_jpeg(f.image, 768)],
        )

    def goto(self, lat: float, lon: float, alt_m: float, speed_ms: float | None) -> Any:
        self.safety.require_actuation()
        self.safety.check_point(lat, lon, alt_m)
        if speed_ms is not None and not 1 <= speed_ms <= self.safety.cfg.max_speed_ms:
            raise InvalidArgument(f"speed_ms must be between 1 and {self.safety.cfg.max_speed_ms:g}")
        self.runner.begin("goto")
        try:
            self.runner.goto_blocking(lat, lon, alt_m, speed_ms)
        finally:
            self.runner.end()
        return self.respond({"arrived": True})

    def return_home(self, wait: bool) -> Any:
        self.safety.require_actuation()
        self.runner.request_abort("return_home requested")
        self.backend.return_to_launch()
        landed = self.runner.wait_landed(600) if wait else False
        return self.respond({"returning": True, "landed": landed})

    def land(self, wait: bool) -> Any:
        self.safety.require_actuation()
        self.runner.request_abort("land requested")
        self.backend.land()
        landed = self.runner.wait_landed(300) if wait else False
        return self.respond({"landing": True, "landed": landed})

    def emergency_stop(self, kill_motors: bool) -> Any:
        # no actuation/simulation gate and no locks: stopping is always allowed
        self.runner.request_abort("emergency_stop")
        self.backend.emergency_stop(kill_motors)
        self.safety.event("emergency_stop" + (" (motors killed)" if kill_motors else " (brake/hover)"))
        return self.respond(
            {
                "stopped": True,
                "kill_motors": kill_motors,
                "next_step": "Vehicle is holding position. Call return_home or land when ready."
                if not kill_motors
                else "Motors cut.",
            }
        )

    def report_finding(self, candidate_id: str, confidence: float, notes: str) -> Any:
        c = self.tracker.get(candidate_id)
        if c is None:
            raise NotFound(f"no candidate {candidate_id!r}")
        if not 0 <= confidence <= 1:
            raise InvalidArgument("confidence must be between 0 and 1")
        finding = {
            "candidate_id": c.id,
            "lat": c.lat,
            "lon": c.lon,
            "confidence": confidence,
            "notes": notes,
            "inspected": c.inspected,
            "closeup_image": c.closeup_path,
            "vision_confidence": c.confidence,
            "reported_at": time.time(),
            "tool_calls_so_far": self.tool_calls,
        }
        if c.closeup_path is None:
            p = self.out_dir / "closeups" / f"thumb_{c.id}.jpg"
            p.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(p), cv2.cvtColor(c.best_crop, cv2.COLOR_RGB2BGR))
            finding["closeup_image"] = str(p)
        c.status = "reported"
        self.findings.append(finding)
        (self.out_dir / "findings.json").write_text(json.dumps(self.findings, indent=1, default=_json_default))
        log.info("finding.reported", candidate=c.id, confidence=confidence)
        payload: dict[str, Any] = {"recorded": finding, "total_findings": len(self.findings)}
        if not c.inspected:
            payload["warning"] = "Reported without a close-up inspection; positions are less accurate."
        return self.respond(payload)


def _r(v: float | None) -> float | None:
    return None if v is None else round(float(v), 3)


def _json_default(o: Any) -> Any:
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, Path):
        return str(o)
    return str(o)


def build_mcp(srv: DroneSearchServer) -> FastMCP:
    mcp = FastMCP("drone-search", instructions=INSTRUCTIONS)
    RO = {"readOnlyHint": True, "destructiveHint": False}
    FLY = {"readOnlyHint": False, "destructiveHint": True}

    @mcp.tool(annotations=RO)
    def get_status() -> Any:
        """Get the drone's live state (position, altitude, battery %, mode, armed), safety limits,
        the current search target, plans, mission progress, top candidates and findings."""
        return srv.call("get_status", srv.get_status)

    @mcp.tool(annotations=RO)
    def set_search_target(
        image_path: Annotated[
            str | None, Field(description="Absolute path to a reference photo of the object.")
        ] = None,
        text: Annotated[
            str | None, Field(description="What to look for, e.g. 'a red backpack'. Colour + object noun works best.")
        ] = None,
        object_size_m: Annotated[
            float | None,
            Field(description="Largest dimension of the object in metres, if known. Drives altitude choice."),
        ] = None,
    ) -> Any:
        """Set what to search for from a reference image, a text description, or both, and
        precompute its embeddings. Returns the label used for matching (inferred from the image
        when no text is given) and the assumed object size. Clears earlier candidates."""
        return srv.call("set_search_target", srv.set_search_target, image_path, text, object_size_m)

    @mcp.tool(annotations=RO)
    def plan_search(
        area_polygon: Annotated[
            list[list[float]] | None, Field(description="Search area as [[lat, lon], ...] (>= 3 points).")
        ] = None,
        center_lat: Annotated[
            float | None, Field(description="Circle centre latitude (alternative to area_polygon).")
        ] = None,
        center_lon: Annotated[float | None, Field(description="Circle centre longitude.")] = None,
        radius_m: Annotated[float | None, Field(description="Circle radius in metres.")] = None,
        altitude_m: Annotated[
            float | None,
            Field(
                description="Search altitude above home. Omit to let the server choose from the target size (recommended)."
            ),
        ] = None,
        overlap: Annotated[float, Field(description="Side overlap between adjacent lanes, 0-0.8.")] = 0.3,
        pattern: Annotated[
            Literal["lawnmower", "spiral"],
            Field(description="lawnmower for even coverage; spiral when the target is likely near the centre."),
        ] = "lawnmower",
        speed_ms: Annotated[
            float, Field(description="Cruise speed; the executor slows down automatically if vision falls behind.")
        ] = 6.0,
    ) -> Any:
        """Plan a coverage pattern over an area without flying. Returns plan_id, altitude, lane
        spacing, camera footprint, expected target size in pixels, path length, estimated time and
        battery use, and whether it fits the geofence and the battery reserve."""
        return srv.call(
            "plan_search",
            srv.plan_search,
            area_polygon,
            center_lat,
            center_lon,
            radius_m,
            altitude_m,
            overlap,
            pattern,
            speed_ms,
        )

    @mcp.tool(annotations=FLY)
    def execute_search(
        plan_id: Annotated[str, Field(description="plan_id returned by plan_search.")],
        max_candidates: Annotated[
            int, Field(description="How many ranked candidates (with thumbnails) to return.", ge=1, le=12)
        ] = 6,
    ) -> Any:
        """Fly a planned search pattern autonomously (takes off if needed) while the vision
        pipeline checks every camera frame. Blocks until the pattern is done or aborted, then
        returns ranked, deduplicated candidates with GPS, confidence and a thumbnail each."""
        return srv.call("execute_search", srv.execute_search, plan_id, max_candidates)

    @mcp.tool(annotations=FLY)
    def inspect_candidate(
        candidate_id: Annotated[str, Field(description="candidate_id from execute_search, e.g. 'c3'.")],
        altitude_m: Annotated[
            float | None, Field(description="Inspection altitude; omit to size it from the object.")
        ] = None,
    ) -> Any:
        """Fly over a candidate, descend while re-centring on it, and capture a close high-res
        image. Returns the close-up image, a refined GPS position and whether vision re-detected
        the object. You decide from the image whether it is the target."""
        return srv.call("inspect_candidate", srv.inspect_candidate, candidate_id, altitude_m)

    @mcp.tool(annotations=RO)
    def capture_image() -> Any:
        """Return the current downward camera frame as an image, with the altitude it was taken at."""
        return srv.call("capture_image", srv.capture_image)

    @mcp.tool(annotations=FLY)
    def goto(
        lat: Annotated[float, Field(description="Latitude, decimal degrees.")],
        lon: Annotated[float, Field(description="Longitude, decimal degrees.")],
        alt_m: Annotated[float, Field(description="Altitude above home in metres.")],
        speed_ms: Annotated[float | None, Field(description="Optional speed in m/s.")] = None,
    ) -> Any:
        """Fly to a GPS point (taking off first if landed) and wait until arrival."""
        return srv.call("goto", srv.goto, lat, lon, alt_m, speed_ms)

    @mcp.tool(annotations=FLY)
    def return_home(wait: Annotated[bool, Field(description="Wait until landed and disarmed.")] = True) -> Any:
        """Abort any running routine, return to the launch point and land there."""
        return srv.call("return_home", srv.return_home, wait)

    @mcp.tool(annotations=FLY)
    def land(wait: Annotated[bool, Field(description="Wait until landed and disarmed.")] = True) -> Any:
        """Abort any running routine and land where the drone is."""
        return srv.call("land", srv.land, wait)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    def emergency_stop(
        kill_motors: Annotated[
            bool, Field(description="false: brake and hover (default). true: cut motors; the drone falls.")
        ] = False,
    ) -> Any:
        """Stop immediately: abort any routine and hold position, or cut the motors. Always available."""
        return srv.call("emergency_stop", srv.emergency_stop, kill_motors)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    def report_finding(
        candidate_id: Annotated[str, Field(description="The candidate you confirmed.")],
        confidence: Annotated[float, Field(description="Your confidence it is the target, 0-1.")],
        notes: Annotated[str, Field(description="What you saw that convinced you.")] = "",
    ) -> Any:
        """Report a confirmed target: records its GPS position and photo as the mission result."""
        return srv.call("report_finding", srv.report_finding, candidate_id, confidence, notes)

    return mcp


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--allow-actuation",
        action="store_true",
        default=os.environ.get("DSM_ALLOW_ACTUATION") == "1",
        help="let tools move the vehicle (simulation only; refused on real vehicles)",
    )
    p.add_argument("--backend", choices=["sitl", "fake"], default=os.environ.get("DSM_BACKEND", "sitl"))
    p.add_argument(
        "--output",
        type=Path,
        default=Path(os.environ.get("DSM_OUTPUT_DIR", Path.cwd() / "output" / time.strftime("%Y%m%d-%H%M%S"))),
    )
    p.add_argument("--no-record", action="store_true")
    p.add_argument("--log-level", default=os.environ.get("DSM_LOG_LEVEL", "INFO"))
    a = p.parse_args(argv)
    _configure_logging(a.log_level)
    backend: DroneBackend
    if a.backend == "sitl":
        from backends.sim import SimBackend

        backend = SimBackend()
    else:
        from backends.fake import FakeBackend

        backend = FakeBackend()
    srv = DroneSearchServer(backend, SafetyConfig(allow_actuation=a.allow_actuation), a.output, record=not a.no_record)
    log.info("server.start", backend=a.backend, actuation=a.allow_actuation, output=str(a.output))
    build_mcp(srv).run(show_banner=False)


if __name__ == "__main__":
    main()


__all__ = ["Aborted", "DroneSearchServer", "build_mcp", "main"]
