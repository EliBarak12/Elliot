"""Autonomous flight routines: fly a coverage plan while the vision pipeline runs, and
inspect a candidate from close up. The LLM chooses *what*; this module flies."""

from __future__ import annotations

import dataclasses
import json
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import structlog

from backends.base import BackendError, DroneBackend, Frame
from common.geo import distance_m, ne_between
from server.errors import Aborted, VehicleError
from server.planner import EnergyModel, SearchPlan
from server.recorder import FlightRecorder
from vision.pipeline import Candidate, CandidateTracker, Detection, FrameAnalyzer

log = structlog.get_logger(__name__)


@dataclass
class SearchReport:
    plan_id: str
    completed: bool
    abort_reason: str | None
    duration_s: float
    frames_analyzed: int
    distance_flown_m: float
    battery_start_pct: float | None
    battery_end_pct: float | None
    coverage_pct: float
    candidates: list[Candidate] = field(default_factory=list)


class MissionRunner:
    """Owns the vehicle while a routine runs. Only one routine at a time."""

    def __init__(self, backend: DroneBackend, recorder: FlightRecorder, energy: EnergyModel) -> None:
        self.backend = backend
        self.recorder = recorder
        self.energy = energy
        self.abort = threading.Event()
        self.abort_reason: str | None = None
        self.active: str | None = None
        self.progress: dict[str, Any] = {}
        self.detection_log: Path | None = None
        self.frame_dump: Path | None = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- basics
    def request_abort(self, reason: str) -> None:
        self.abort_reason = reason
        self.abort.set()
        log.warning("mission.abort_requested", reason=reason)

    def _check_abort(self) -> None:
        if self.abort.is_set():
            raise Aborted(self.abort_reason or "aborted")

    def begin(self, name: str) -> None:
        with self._lock:
            if self.active:
                from server.errors import StateConflict

                raise StateConflict(
                    f"'{self.active}' is already running",
                    next_step="Wait for it to finish, or call emergency_stop / return_home.",
                )
            self.active = name
            self.abort.clear()
            self.abort_reason = None

    def end(self) -> None:
        with self._lock:
            self.active = None

    def _sleep(self, s: float) -> None:
        if self.abort.wait(s):
            raise Aborted(self.abort_reason or "aborted")

    def _observe_energy(self) -> None:
        t = self.backend.telemetry()
        self.energy.observe(time.time(), t.battery_pct, t.armed and (t.alt_rel_m or 0) > 1)

    def ensure_airborne(self, alt_m: float) -> None:
        t = self.backend.telemetry()
        if t.armed and (t.alt_rel_m or 0) > 1.5 and t.mode in ("GUIDED", "BRAKE", "LOITER"):
            return
        if t.armed and (t.alt_rel_m or 0) > 1.5:
            self.backend.set_mode("GUIDED")
            return
        log.info("mission.takeoff", alt_m=alt_m)
        try:
            # earth-frame (stabilised) nadir; the boot-time NEUTRAL pose is body-frame only
            self.backend.set_gimbal_nadir()
            self.backend.arm_and_takeoff(alt_m)
        except BackendError as exc:
            raise VehicleError(f"takeoff failed: {exc}") from exc
        t0 = time.time()
        while (self.backend.telemetry().alt_rel_m or 0) < alt_m * 0.92:
            self._check_abort()
            if time.time() - t0 > 90:
                raise VehicleError("did not reach take-off altitude within 90 s")
            self._sleep(0.3)

    def fly_to(
        self,
        lat: float,
        lon: float,
        alt: float,
        speed: float | None = None,
        tol_m: float = 1.5,
        timeout_s: float = 300,
        on_tick: Callable[[], None] | None = None,
    ) -> None:
        try:
            self.backend.goto(lat, lon, alt, speed)
        except BackendError as exc:
            raise VehicleError(f"goto rejected: {exc}") from exc
        t0 = time.time()
        while True:
            self._check_abort()
            t = self.backend.telemetry()
            if t.mode != "GUIDED":
                raise Aborted(f"vehicle left GUIDED mode (now {t.mode})")
            if t.lat is not None and t.alt_rel_m is not None:
                d = distance_m(t.lat, t.lon, lat, lon)  # type: ignore[arg-type]
                if d < tol_m and abs(t.alt_rel_m - alt) < 1.5:
                    return
            if time.time() - t0 > timeout_s:
                raise VehicleError(f"did not reach waypoint within {timeout_s:.0f} s")
            if on_tick:
                on_tick()
            self._observe_energy()
            time.sleep(0.05)

    # ---------------------------------------------------------------- search
    def run_search(
        self,
        plan: SearchPlan,
        analyzer: FrameAnalyzer,
        tracker: CandidateTracker,
    ) -> SearchReport:
        t_start = time.time()
        b0 = self.backend.telemetry().battery_pct
        frames: dict[str, float] = {"n": 0, "last_seq": -1, "analysis_s": 0.0, "last_t": 0.0}
        flown: dict[str, Any] = {"m": 0.0, "last": None}
        covered: set[tuple[int, int]] = set()
        cell = 4.0  # coverage grid, metres
        home = self.backend.telemetry()
        ref_lat, ref_lon = home.home_lat or home.lat, home.home_lon or home.lon
        if ref_lat is None or ref_lon is None:
            raise VehicleError("no home/GPS position; cannot run a search")
        ref = (ref_lat, ref_lon)

        def analyze_latest() -> None:
            f: Frame | None = self.backend.latest_frame(max_age_s=1.5)
            if f is None or f.seq == frames["last_seq"]:
                return
            frames["last_seq"] = f.seq
            p = f.pose
            if p.alt_rel_m is None or p.alt_rel_m < plan.altitude_m * 0.8:
                return
            self._save_frame(f)
            dets = analyzer.analyze(f)
            # Analysis interval in *vehicle* time (frame stamps): the drone flies in sim time,
            # and with the simulator at 0.3x real time a wall-clock measure slowed it to
            # 2.9 m/s although vision kept up (v3 easy-5000). On hardware both clocks agree.
            if frames["last_t"] > 0:
                dt = max(0.05, f.timestamp - frames["last_t"])
                frames["analysis_s"] = 0.8 * frames["analysis_s"] + 0.2 * dt if frames["analysis_s"] else dt
            frames["last_t"] = f.timestamp
            tracker.note_coverage(f)
            tracker.add(dets)
            self._log_detections(f, dets)
            frames["n"] += 1
            self._mark_coverage(f, ref, covered, cell)
            self.recorder.note_detections(f, dets)
            self.progress.update(frames_analyzed=frames["n"], candidates=len(tracker.candidates))

        # Analysis runs on its own thread so slow inference never delays flight commands.
        stop_vision = threading.Event()

        def vision_loop() -> None:
            while not stop_vision.is_set():
                try:
                    analyze_latest()
                except Exception:
                    log.error("mission.vision.error", exc_info=True)
                    time.sleep(0.5)
                time.sleep(0.02)

        completed, reason = False, None
        self.recorder.start(f"search_{plan.id}")
        try:
            self.ensure_airborne(plan.altitude_m)
            th = threading.Thread(target=vision_loop, daemon=True, name="vision")
            th.start()
            n = len(plan.waypoints)
            for i, (lat, lon) in enumerate(plan.waypoints):
                self.progress.update(waypoint=i + 1, of=n)
                self.fly_to(
                    lat,
                    lon,
                    plan.altitude_m,
                    self._speed_for(plan, frames["analysis_s"]),
                    tol_m=2.5,
                    on_tick=lambda: tick_light(flown, self.backend),
                )
            completed = True
        except Aborted as exc:
            reason = exc.message
        finally:
            stop_vision.set()
            self.recorder.stop()
        area_cells = max(1.0, plan.area_m2 / (cell * cell))
        report = SearchReport(
            plan.id,
            completed,
            reason,
            time.time() - t_start,
            int(frames["n"]),
            flown["m"],
            b0,
            self.backend.telemetry().battery_pct,
            min(100.0, 100 * len(covered) / area_cells),
            tracker.ranked(),
        )
        log.info(
            "mission.search.complete",
            plan_id=plan.id,
            completed=completed,
            reason=reason,
            frames=frames["n"],
            candidates=len(report.candidates),
        )
        return report

    def _save_frame(self, f: Frame) -> None:
        """Optionally keep full-resolution frames + poses for offline vision benchmarks."""
        if self.frame_dump is None:
            return
        self.frame_dump.mkdir(parents=True, exist_ok=True)
        name = f"{f.seq:06d}.jpg"
        cv2.imwrite(
            str(self.frame_dump / name), cv2.cvtColor(f.image, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92]
        )
        p = f.pose
        with open(self.frame_dump / "frames.jsonl", "a") as fh:
            fh.write(
                json.dumps(
                    {
                        "file": name,
                        "seq": f.seq,
                        "t": f.timestamp,
                        "camera": dataclasses.asdict(f.camera),
                        "pose": {k: v for k, v in p.as_dict().items() if k != "status_text"},
                    }
                )
                + "\n"
            )

    def _log_detections(self, f: Frame, dets: list[Detection]) -> None:
        """Append every detection with the pose it was projected from (offline diagnosis)."""
        if self.detection_log is None or not dets:
            return
        p = f.pose
        with open(self.detection_log, "a") as fh:
            for d in dets:
                fh.write(
                    json.dumps(
                        {
                            "seq": f.seq,
                            "t": f.timestamp,
                            "lat": d.lat,
                            "lon": d.lon,
                            "score": round(d.score, 3),
                            "text": d.cues.text,
                            "image": d.cues.image,
                            "color": d.cues.color,
                            "size_m": round(d.size_m, 2),
                            "u": round(d.pixel[0], 1),
                            "v": round(d.pixel[1], 1),
                            "cand": d.candidate_id,
                            "drone": [p.lat, p.lon, p.alt_rel_m],
                            "yaw": round(p.yaw_rad, 4),
                            "roll": round(p.roll_rad, 4),
                            "pitch": round(p.pitch_rad, 4),
                            "rate_dps": round(p.tilt_rate_dps, 2),
                            "speed": round(p.groundspeed_ms, 2),
                        }
                    )
                    + "\n"
                )

    def _speed_for(self, plan: SearchPlan, analysis_s: float) -> float:
        """Slow down if vision can't keep up: each ground spot should be analysed in >= 2 frames."""
        if analysis_s <= 0:
            return plan.speed_ms
        along = plan.footprint_m[1]
        v = along / 2.0 / max(analysis_s, 0.05)
        return float(np.clip(min(plan.speed_ms, v), 2.0, plan.speed_ms))

    @staticmethod
    def _mark_coverage(f: Frame, ref: tuple[float, float], covered: set[tuple[int, int]], cell: float) -> None:
        p = f.pose
        if p.lat is None or p.lon is None or p.alt_rel_m is None:
            return
        n0, e0 = ne_between(ref[0], ref[1], p.lat, p.lon)
        hw = f.camera.width / 2 * p.alt_rel_m / f.camera.fx
        hh = f.camera.height / 2 * p.alt_rel_m / f.camera.fy
        c, s = math.cos(p.yaw_rad), math.sin(p.yaw_rad)
        for fwd in np.arange(-hh, hh, cell):
            for right in np.arange(-hw, hw, cell):
                n = n0 + fwd * c - right * s
                e = e0 + fwd * s + right * c
                covered.add((int(n // cell), int(e // cell)))

    # --------------------------------------------------------------- inspect
    def run_inspect(
        self,
        cand: Candidate,
        analyzer: FrameAnalyzer,
        search_alt: float,
        inspect_alt: float,
        out_dir: Path,
    ) -> dict[str, Any]:
        self.recorder.start(f"inspect_{cand.id}")
        try:
            self.ensure_airborne(search_alt)
            t = self.backend.telemetry()
            cruise = max(search_alt, t.alt_rel_m or search_alt)
            self.fly_to(cand.lat, cand.lon, cruise, 5.0, tol_m=1.5)
            # Descend in steps, re-acquiring the object *visually* each time. The candidate's
            # GPS was measured minutes ago and GPS drifts (~1-2 m over minutes), so search the
            # whole frame and prefer strong detections close to where we expect it.
            lat, lon = cand.lat, cand.lon
            refined: list[Detection] = []
            steps = [a for a in (max(inspect_alt, min(cruise, 14.0)), inspect_alt) if a < cruise + 0.5]
            for alt in dict.fromkeys(steps or [inspect_alt]):
                self.fly_to(lat, lon, alt, 2.0, tol_m=0.8)
                self._sleep(1.5)
                found = self._reacquire(analyzer, lat, lon, cand.size_m, n_frames=4)
                if found:
                    w = np.array([d.score for d in found])
                    lat = float(np.dot(w, [d.lat for d in found]) / w.sum())
                    lon = float(np.dot(w, [d.lon for d in found]) / w.sum())
                    refined = found
            self.fly_to(lat, lon, inspect_alt, 1.5, tol_m=0.5)
            self._sleep(1.5)
            zoom = self._zoom_in(analyzer, cand, lat, lon, inspect_alt)
            if zoom["lat"] is not None:
                lat, lon = zoom["lat"], zoom["lon"]
            f = self._fresh_frame(6.0)
            if f is None:
                raise VehicleError("no camera frame at the inspection point for 6 s (video link down?)")
            # crop from detections in *this* frame (boxes from earlier frames do not apply)
            final = self._pick(analyzer.analyze(f), lat, lon, cand.size_m)
            closeup, box = self._closeup(f, final, lat, lon, cand.size_m)
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"closeup_{cand.id}.jpg"
            cv2.imwrite(str(path), cv2.cvtColor(closeup, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
            full = out_dir / f"closeup_{cand.id}_frame.jpg"
            cv2.imwrite(str(full), cv2.cvtColor(f.image, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
            best = max(refined, key=lambda d: d.score) if refined else None
            moved = distance_m(cand.lat, cand.lon, lat, lon)
            return {
                "closeup": closeup,
                "full_frame": f.image,
                "object_in_final_frame": bool(final),
                "closeup_path": str(path),
                "frame_path": str(full),
                "lat": lat,
                "lon": lon,
                "refined_shift_m": moved,
                "redetected": bool(refined),
                "closeup_score": best.score if best else None,
                "alt_m": f.pose.alt_rel_m,
                "zoom": zoom["zoom"],
                "cues": best.cues if best else None,
            }
        finally:
            if self.backend.max_zoom > 1.0:
                self.backend.set_zoom(1.0)
            self.recorder.stop()

    def _zoom_in(
        self, analyzer: FrameAnalyzer, cand: Candidate, lat: float, lon: float, alt: float, target_px: float = 220.0
    ) -> dict[str, Any]:
        """Optical zoom until the object spans ~target_px, re-centring halfway (a narrow
        field of view leaves little room for hover drift)."""
        out: dict[str, Any] = {"zoom": 1.0, "lat": None, "lon": None}
        f = self._fresh_frame(4.0)
        if self.backend.max_zoom <= 1.0 or f is None:
            return out
        base_fx = f.camera.fx
        want = float(np.clip(target_px / (cand.size_m * base_fx / alt), 1.0, self.backend.max_zoom))
        if want < 1.3:
            return out
        for z in (want**0.5, want):
            applied = self.backend.set_zoom(z)
            self._wait_zoom(base_fx * applied)
            found = self._reacquire(analyzer, lat, lon, cand.size_m, n_frames=3)
            if found:
                w = np.array([d.score for d in found])
                lat = float(np.dot(w, [d.lat for d in found]) / w.sum())
                lon = float(np.dot(w, [d.lon for d in found]) / w.sum())
                out.update(lat=lat, lon=lon)
                self.fly_to(lat, lon, alt, 1.0, tol_m=0.3)
                self._sleep(1.0)
            out["zoom"] = applied
        return out

    def _fresh_frame(self, timeout_s: float) -> Frame | None:
        """Wait for a usable frame: real video links drop and delay frames, and a frame is
        unusable until the pose stream covers its exposure time."""
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            self._check_abort()
            f = self.backend.latest_frame(max_age_s=1.5)
            if f is not None:
                return f
            time.sleep(0.1)
        return None

    def _wait_zoom(self, fx_target: float, timeout_s: float = 5.0) -> None:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            self._check_abort()
            f = self.backend.latest_frame(max_age_s=1.0)
            if f is not None and abs(f.camera.fx / fx_target - 1.0) < 0.02:
                return
            time.sleep(0.1)
        log.warning("mission.zoom.timeout", fx_target=round(fx_target, 1))

    def _reacquire(
        self, analyzer: FrameAnalyzer, lat: float, lon: float, size_m: float, n_frames: int
    ) -> list[Detection]:
        """Detections of the object over a few frames, searched across the whole frame."""
        out: list[Detection] = []
        last = -1
        t0 = time.time()
        while time.time() - t0 < 12 and n_frames > 0:
            self._check_abort()
            f = self.backend.latest_frame(max_age_s=1.0)
            if f is None or f.seq == last:
                time.sleep(0.1)
                continue
            last = f.seq
            n_frames -= 1
            dets = analyzer.analyze(f)
            self.recorder.note_detections(f, dets)
            out += self._pick(dets, lat, lon, size_m)
        if not out:
            return []
        # keep the cluster around the strongest re-acquisition, drop stray blobs
        best = max(out, key=lambda d: d.score)
        r = max(2.0, size_m)
        return [d for d in out if distance_m(d.lat, d.lon, best.lat, best.lon) < r]

    @staticmethod
    def _pick(dets: list[Detection], lat: float, lon: float, size_m: float, drift_m: float = 6.0) -> list[Detection]:
        """The detection most likely to be our object: score weighted by distance from the
        expected position on a GPS-drift scale. Returns [] or [best]."""
        if not dets:
            return []

        def weight(d: Detection) -> float:
            dist = distance_m(d.lat, d.lon, lat, lon)
            return d.score * float(np.exp(-0.5 * (dist / (drift_m + size_m)) ** 2))

        best = max(dets, key=weight)
        return [best] if weight(best) > 0.1 else []

    @staticmethod
    def _closeup(
        f: Frame, dets: list[Detection], lat: float, lon: float, size_m: float
    ) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        """Crop of the full-resolution frame around the object (or the image centre)."""
        h, w = f.image.shape[:2]
        alt = f.pose.alt_rel_m or 10.0
        px_per_m = f.camera.fx / alt
        half = int(np.clip(size_m * px_per_m * 2.0, 96, 360))
        if dets:
            d = max(dets, key=lambda d: d.score)
            x0, y0, x1, y1 = d.bbox
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        else:
            cx, cy = w // 2, h // 2
        x0, y0 = max(0, cx - half), max(0, cy - half)
        x1, y1 = min(w, cx + half), min(h, cy + half)
        crop = f.image[y0:y1, x0:x1]
        if max(crop.shape[:2]) < 384:
            s = 384 / max(crop.shape[:2])
            crop = cv2.resize(crop, (int(crop.shape[1] * s), int(crop.shape[0] * s)), interpolation=cv2.INTER_CUBIC)
        return crop, (x0, y0, x1, y1)

    # --------------------------------------------------------------- simple legs
    def goto_blocking(self, lat: float, lon: float, alt: float, speed: float | None) -> None:
        self.recorder.start("goto")
        try:
            self.ensure_airborne(alt)
            self.fly_to(lat, lon, alt, speed, tol_m=1.5, on_tick=lambda: tick_light({}, self.backend))
        finally:
            self.recorder.stop()

    def wait_landed(self, timeout_s: float = 600) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            t = self.backend.telemetry()
            if not t.armed and (t.alt_rel_m or 0) < 1.0:
                return True
            self._observe_energy()
            time.sleep(0.5)
        return False


def tick_light(state: dict[str, Any], backend: DroneBackend) -> None:
    """Cheap per-loop bookkeeping on the flight thread (distance flown)."""
    t = backend.telemetry()
    if t.lat is None or not isinstance(state, dict) or "m" not in state:
        return
    if state.get("last") is not None:
        state["m"] += distance_m(state["last"][0], state["last"][1], t.lat, t.lon)  # type: ignore[arg-type]
    state["last"] = (t.lat, t.lon)
