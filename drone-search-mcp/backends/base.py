"""Backend interface: the only thing the server knows about the aircraft.

A backend moves the vehicle and reports what it measures. It does not decide anything:
safety policy, mission logic and vision all live above it, so swapping SITL for real
ArduPilot hardware (or a Tello) means writing one class, not touching the tools.

Every method is synchronous and thread-safe; the server calls them from worker threads.
Movement commands are *non-blocking*: they return once the autopilot acknowledged the
command, and the server polls ``telemetry()`` to wait for the outcome. That keeps
``emergency_stop`` responsive - nothing in a backend ever sleeps on a long flight leg.
"""

from __future__ import annotations

import abc
from dataclasses import asdict, dataclass, field

import numpy as np


class BackendError(RuntimeError):
    """The vehicle refused or did not acknowledge a command, or the link is down."""


@dataclass
class Telemetry:
    lat: float | None = None
    lon: float | None = None
    alt_rel_m: float | None = None  # above home
    alt_amsl_m: float | None = None
    heading_deg: float | None = None
    roll_rad: float = 0.0
    pitch_rad: float = 0.0
    yaw_rad: float = 0.0
    roll_rate: float = 0.0  # rad/s, body
    pitch_rate: float = 0.0
    yaw_rate: float = 0.0
    vn_ms: float = 0.0
    ve_ms: float = 0.0
    vd_ms: float = 0.0
    battery_pct: float | None = None
    battery_v: float | None = None
    current_a: float | None = None
    mode: str = "UNKNOWN"
    armed: bool = False
    gps_fix: int = 0
    satellites: int = 0
    ekf_ok: bool = False
    home_lat: float | None = None
    home_lon: float | None = None
    home_alt_amsl_m: float | None = None
    gimbal_pitch_deg: float | None = None
    gimbal_yaw_deg: float | None = None  # body frame
    time_boot_s: float = 0.0  # vehicle clock (sim time in SITL lockstep)
    wall_time: float = 0.0  # when this snapshot was last updated
    status_text: list[str] = field(default_factory=list)

    @property
    def tilt_rate_dps(self) -> float:
        """Body rotation rate in deg/s; frames taken while this is high are blurred in pose."""
        return float(np.degrees(np.sqrt(self.roll_rate**2 + self.pitch_rate**2 + self.yaw_rate**2)))

    @property
    def groundspeed_ms(self) -> float:
        return float(np.hypot(self.vn_ms, self.ve_ms))

    def as_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["groundspeed_ms"] = round(self.groundspeed_ms, 2)
        return d


@dataclass(frozen=True)
class CameraModel:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float


@dataclass
class Frame:
    image: np.ndarray  # HxWx3 RGB uint8
    camera: CameraModel
    seq: int
    timestamp: float  # vehicle clock seconds, comparable to Telemetry.time_boot_s
    wall_time: float
    pose: Telemetry  # vehicle state interpolated at the exposure time


class DroneBackend(abc.ABC):
    """Interface every vehicle backend implements."""

    name: str = "abstract"

    @abc.abstractmethod
    def connect(self, timeout_s: float = 30.0) -> None: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    @abc.abstractmethod
    def telemetry(self) -> Telemetry:
        """Latest state. Never blocks on the link."""

    @abc.abstractmethod
    def is_simulation(self) -> bool:
        """True only when the vehicle itself proves it is simulated (e.g. SITL SIMSTATE)."""

    @abc.abstractmethod
    def arm_and_takeoff(self, alt_m: float) -> None: ...

    @abc.abstractmethod
    def goto(self, lat: float, lon: float, alt_rel_m: float, speed_ms: float | None = None) -> None:
        """Start flying to a point; returns once commanded."""

    @abc.abstractmethod
    def set_mode(self, mode: str, timeout_s: float = 5.0) -> None:
        """Switch flight mode by ArduPilot-style name (GUIDED, BRAKE, RTL, LAND)."""

    @abc.abstractmethod
    def hold(self) -> None:
        """Stop and hover in place (brake)."""

    @abc.abstractmethod
    def return_to_launch(self) -> None: ...

    @abc.abstractmethod
    def land(self) -> None: ...

    @abc.abstractmethod
    def emergency_stop(self, kill_motors: bool) -> None:
        """Hover in place, or cut the motors. Must not wait on any other command."""

    @abc.abstractmethod
    def latest_frame(self, max_age_s: float = 2.0) -> Frame | None:
        """Most recent camera frame with the pose it was taken at, or None if stale."""

    def set_gimbal_nadir(self) -> None:  # noqa: B027 - optional capability
        """Point the camera straight down (no-op where the mount is fixed)."""
