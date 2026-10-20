"""FakeBackend: an in-process kinematic drone with a synthetic top-down camera.

For unit tests and quick demos only - no physics, no autopilot. It renders flat coloured
objects on textured grass so the whole server (planning, mission execution, vision,
projection, deduplication) can be exercised in seconds without SITL or Gazebo.
"""

from __future__ import annotations

import dataclasses
import math
import threading
import time
from typing import Any

import numpy as np

from backends.base import BackendError, CameraModel, DroneBackend, Frame, Telemetry
from common.geo import ne_between, offset

HOME = (47.397742, 8.545594)


@dataclasses.dataclass
class FakeObject:
    north_m: float
    east_m: float
    size_m: float
    color: tuple[int, int, int]


class FakeBackend(DroneBackend):
    name = "fake"
    max_zoom = 4.0

    def __init__(
        self,
        objects: list[FakeObject] | None = None,
        speedup: float = 1.0,
        camera: tuple[int, int, float] = (640, 480, 1.2),
        battery_pct_per_min: float = 7.0,
    ) -> None:
        self.objects = objects or []
        self.speedup = speedup
        w, h, hfov = camera
        f = w / 2 / math.tan(hfov / 2)
        self.cam = CameraModel(w, h, f, f, w / 2, h / 2)
        self.battery_rate = battery_pct_per_min
        self._t = Telemetry(
            lat=HOME[0],
            lon=HOME[1],
            alt_rel_m=0.0,
            heading_deg=0.0,
            battery_pct=100.0,
            mode="STABILIZE",
            gps_fix=3,
            satellites=12,
            ekf_ok=True,
            home_lat=HOME[0],
            home_lon=HOME[1],
            home_alt_amsl_m=488.0,
            gimbal_pitch_deg=-90.0,
        )
        self._target: tuple[float, float, float] | None = None
        self._hold_yaw: float | None = None
        self._speed = 5.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seq = 0
        self._sim_time = 0.0
        rng = np.random.default_rng(0)
        self._grass = (rng.normal(0, 8, (64, 64, 3)) + np.array([70, 120, 50])).clip(0, 255).astype(np.uint8)
        self.commands: list[str] = []
        self.zoom = 1.0

    def connect(self, timeout_s: float = 30.0) -> None:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(2)
        self._thread = None

    def telemetry(self) -> Telemetry:
        with self._lock:
            return dataclasses.replace(self._t, status_text=list(self._t.status_text))

    def is_simulation(self) -> bool:
        return True

    def _loop(self) -> None:
        dt = 0.05
        while not self._stop.wait(dt / self.speedup):
            with self._lock:
                self._step(dt)

    def _step(self, dt: float) -> None:
        t = self._t
        self._sim_time += dt
        t.time_boot_s = self._sim_time
        t.wall_time = time.time()
        assert t.lat is not None and t.lon is not None and t.alt_rel_m is not None
        if t.mode == "RTL":
            self._target = (HOME[0], HOME[1], max(t.alt_rel_m, 15.0))
            n, e = ne_between(t.lat, t.lon, HOME[0], HOME[1])
            if math.hypot(n, e) < 1.0:
                t.mode = "LAND"
        if t.mode == "LAND":
            self._target = (t.lat, t.lon, 0.0)
        if t.mode == "BRAKE":
            self._target = None
        if t.armed and self._target is not None:
            lat, lon, alt = self._target
            n, e = ne_between(t.lat, t.lon, lat, lon)
            d = math.hypot(n, e)
            step = min(d, self._speed * dt)
            if d > 0.05:
                t.lat, t.lon = offset(t.lat, t.lon, n / d * step, e / d * step)
                t.yaw_rad = math.atan2(e, n) if self._hold_yaw is None else self._hold_yaw
                t.heading_deg = math.degrees(t.yaw_rad) % 360
                t.vn_ms, t.ve_ms = n / d * self._speed, e / d * self._speed
            else:
                t.vn_ms = t.ve_ms = 0.0
            dz = alt - t.alt_rel_m
            t.alt_rel_m += float(np.clip(dz, -1.5 * dt, 2.5 * dt))
        if t.armed and t.mode == "LAND" and t.alt_rel_m < 0.1:
            t.armed, t.alt_rel_m = False, 0.0
        if t.armed and t.battery_pct is not None:
            t.battery_pct = max(0.0, t.battery_pct - self.battery_rate / 60 * dt)
        if t.armed and t.alt_rel_m > 0.5:
            self._seq += 1 if int(self._sim_time * 5) != int((self._sim_time - dt) * 5) else 0

    def arm_and_takeoff(self, alt_m: float) -> None:
        self.commands.append(f"takeoff {alt_m}")
        with self._lock:
            self._t.armed = True
            self._t.mode = "GUIDED"
            self._target = (self._t.lat, self._t.lon, alt_m)  # type: ignore[assignment]

    def goto(
        self, lat: float, lon: float, alt_rel_m: float, speed_ms: float | None = None, yaw_deg: float | None = None
    ) -> None:
        with self._lock:
            if not self._t.armed:
                raise BackendError("not armed")
            self._t.mode = "GUIDED"
            self._target = (lat, lon, alt_rel_m)
            self._hold_yaw = None if yaw_deg is None else math.radians(yaw_deg)
            if speed_ms:
                self._speed = speed_ms

    def set_mode(self, mode: str, timeout_s: float = 5.0) -> None:
        self.commands.append(f"mode {mode}")
        with self._lock:
            self._t.mode = mode

    def hold(self) -> None:
        with self._lock:
            self._target = (self._t.lat, self._t.lon, self._t.alt_rel_m)  # type: ignore[assignment]

    def return_to_launch(self) -> None:
        self.set_mode("RTL")

    def land(self) -> None:
        self.set_mode("LAND")

    def emergency_stop(self, kill_motors: bool) -> None:
        self.commands.append(f"estop kill={kill_motors}")
        with self._lock:
            if kill_motors:
                self._t.armed = False
                self._t.alt_rel_m = 0.0
            self._t.mode = "BRAKE"
            self._target = None

    def set_zoom(self, zoom: float) -> float:
        self.zoom = float(min(max(zoom, 1.0), self.max_zoom))
        return self.zoom

    def camera(self) -> CameraModel:
        c = self.cam
        return CameraModel(c.width, c.height, c.fx * self.zoom, c.fy * self.zoom, c.cx, c.cy)

    def render(self, pose: Telemetry) -> np.ndarray:
        w, h = self.cam.width, self.cam.height
        cam = self.camera()
        img = np.tile(self._grass, (h // 64 + 1, w // 64 + 1, 1))[:h, :w].copy()
        alt = max(pose.alt_rel_m or 0.0, 0.5)
        c, s = math.cos(pose.yaw_rad), math.sin(pose.yaw_rad)
        for o in self.objects:
            n, e = ne_between(pose.lat, pose.lon, *offset(HOME[0], HOME[1], o.north_m, o.east_m))  # type: ignore[arg-type]
            fwd, right = n * c + e * s, -n * s + e * c
            u = cam.cx + right / alt * cam.fx
            v = cam.cy - fwd / alt * cam.fy
            r = max(1, int(o.size_m / 2 / alt * cam.fx))
            x0, x1 = int(u - r), int(u + r)
            y0, y1 = int(v - r), int(v + r)
            if x1 < 0 or y1 < 0 or x0 >= w or y0 >= h:
                continue
            img[max(0, y0) : max(0, y1), max(0, x0) : max(0, x1)] = o.color
        return img

    def latest_frame(self, max_age_s: float = 2.0) -> Frame | None:
        t = self.telemetry()
        return Frame(self.render(t), self.camera(), int(t.time_boot_s * 5), t.time_boot_s, time.time(), t)

    def debug(self) -> dict[str, Any]:
        return {"target": self._target, "speed": self._speed}
