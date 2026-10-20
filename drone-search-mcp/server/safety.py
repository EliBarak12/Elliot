"""Safety policy, enforced in code below every tool.

Design follows mavlink-mcp (MIT, studied not copied): actuation is opt-in, simulation is
proven by the vehicle rather than the connection string, out-of-envelope requests are
refused with a reason instead of silently clamped, and the autopilot's own fence and
GCS-heartbeat failsafe stay underneath as a second layer (set in sim/params).

On top of that, for autonomous search:
* geofence: every commanded point must be within ``max_radius_m`` of home (and inside an
  optional polygon); a plan whose path leaves the fence is refused before take-off.
* altitude band: [min_alt_m, max_alt_m] above home for any commanded flight leg.
* battery reserve: a monitor thread aborts whatever is running and returns to launch when
  the battery drops to ``battery_reserve_pct`` (30%), and plans that would end below the
  reserve are refused up front.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import structlog

from backends.base import DroneBackend, Telemetry
from common.geo import distance_m
from server.errors import ActuationDisabled, NotSimulation, SafetyViolation

log = structlog.get_logger(__name__)


@dataclass
class SafetyConfig:
    allow_actuation: bool = False
    max_radius_m: float = 250.0
    min_alt_m: float = 8.0
    max_alt_m: float = 60.0
    battery_reserve_pct: float = 30.0
    max_speed_ms: float = 10.0
    fence_polygon: list[tuple[float, float]] | None = None


@dataclass
class SafetyState:
    reserve_triggered: bool = False
    reserve_triggered_at: float | None = None
    last_violation: str | None = None
    events: list[str] = field(default_factory=list)


def point_in_polygon(lat: float, lon: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi:
            inside = not inside
        j = i
    return inside


class SafetyGate:
    def __init__(self, cfg: SafetyConfig, backend: DroneBackend) -> None:
        self.cfg = cfg
        self.backend = backend
        self.state = SafetyState()
        self.home_wait_s = 30.0
        self._monitor: threading.Thread | None = None
        self._stop = threading.Event()
        self._on_reserve: list[Callable[[], None]] = []

    # ---------------------------------------------------------------- checks
    def require_actuation(self) -> None:
        if not self.cfg.allow_actuation:
            raise ActuationDisabled("vehicle actuation is disabled on this server")
        if not self.backend.is_simulation():
            raise NotSimulation(
                "the connected vehicle has not proven it is a simulator (no SITL SIMSTATE "
                "messages); this server never flies a real vehicle"
            )

    def check_point(self, lat: float, lon: float, alt_m: float, what: str = "target") -> None:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise SafetyViolation(
                f"{what} latitude/longitude out of range: {lat}, {lon}",
                next_step="Pass decimal degrees, latitude first.",
            )
        if not self.cfg.min_alt_m <= alt_m <= self.cfg.max_alt_m:
            raise SafetyViolation(
                f"{what} altitude {alt_m:g} m is outside the allowed band "
                f"[{self.cfg.min_alt_m:g}, {self.cfg.max_alt_m:g}] m above home",
                next_step=f"Choose an altitude between {self.cfg.min_alt_m:g} and {self.cfg.max_alt_m:g} m.",
            )
        t = self.backend.telemetry()
        # ArduPilot sets home only once EKF3 has a GPS origin, which can lag boot by tens of
        # seconds (agents saw "home position unknown" on their first plan, run easy-6000).
        deadline = time.time() + self.home_wait_s
        while (t.home_lat is None or t.home_lon is None) and time.time() < deadline:
            time.sleep(0.5)
            t = self.backend.telemetry()
        if t.home_lat is None or t.home_lon is None:
            raise SafetyViolation(
                "home position unknown, cannot evaluate the geofence (failing closed)",
                next_step="Wait a few seconds for GPS/home, then retry.",
            )
        d = distance_m(t.home_lat, t.home_lon, lat, lon)
        if d > self.cfg.max_radius_m:
            raise SafetyViolation(
                f"{what} is {d:.0f} m from home, beyond the {self.cfg.max_radius_m:.0f} m geofence",
                next_step="Pick a point inside the geofence (see get_status.safety.geofence).",
            )
        if self.cfg.fence_polygon and not point_in_polygon(lat, lon, self.cfg.fence_polygon):
            raise SafetyViolation(f"{what} is outside the geofence polygon")

    def check_battery_for(self, needed_pct: float) -> None:
        t = self.backend.telemetry()
        if t.battery_pct is None:
            raise SafetyViolation("battery level unknown (failing closed)")
        left = t.battery_pct - needed_pct
        if left < self.cfg.battery_reserve_pct:
            raise SafetyViolation(
                f"estimated to need {needed_pct:.0f}% battery but only "
                f"{t.battery_pct - self.cfg.battery_reserve_pct:.0f}% is available above the "
                f"{self.cfg.battery_reserve_pct:.0f}% reserve",
                next_step="Plan a smaller area, fly higher (wider footprint), or lower the overlap.",
            )

    def describe(self) -> dict[str, object]:
        t = self.backend.telemetry()
        return {
            "actuation_enabled": self.cfg.allow_actuation,
            "is_simulation": self.backend.is_simulation(),
            "geofence": {"center": [t.home_lat, t.home_lon], "radius_m": self.cfg.max_radius_m},
            "altitude_band_m": [self.cfg.min_alt_m, self.cfg.max_alt_m],
            "battery_reserve_pct": self.cfg.battery_reserve_pct,
            "reserve_triggered": self.state.reserve_triggered,
            "recent_events": self.state.events[-5:],
        }

    # --------------------------------------------------------------- monitor
    def on_reserve(self, cb: Callable[[], None]) -> None:
        self._on_reserve.append(cb)

    def start_monitor(self) -> None:
        if self._monitor and self._monitor.is_alive():
            return
        self._stop.clear()
        self._monitor = threading.Thread(target=self._run, daemon=True, name="safety-monitor")
        self._monitor.start()

    def stop_monitor(self) -> None:
        self._stop.set()

    def event(self, msg: str) -> None:
        self.state.events.append(f"{time.strftime('%H:%M:%S')} {msg}")
        log.warning("safety.event", detail=msg)

    def _run(self) -> None:
        while not self._stop.wait(0.5):
            try:
                t: Telemetry = self.backend.telemetry()
                airborne = t.armed and (t.alt_rel_m or 0) > 1.0
                if (
                    airborne
                    and t.battery_pct is not None
                    and t.battery_pct <= self.cfg.battery_reserve_pct
                    and not self.state.reserve_triggered
                ):
                    self.state.reserve_triggered = True
                    self.state.reserve_triggered_at = time.time()
                    # abort the running routine first so it cannot re-command GUIDED, then RTL;
                    # bookkeeping last, so a logging problem can never stop the return
                    for cb in self._on_reserve:
                        cb()
                    if self.cfg.allow_actuation:
                        self.backend.return_to_launch()
                    self.event(
                        f"battery {t.battery_pct:.0f}% <= reserve "
                        f"{self.cfg.battery_reserve_pct:.0f}%: aborted and returning to launch"
                    )
            except Exception:  # the monitor must survive anything
                log.error("safety.monitor.error", exc_info=True)
