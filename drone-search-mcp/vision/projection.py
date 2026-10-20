"""Pixel -> ground GPS projection for a gimbal camera over flat terrain.

Frames (all right-handed):
* image:  u right, v down (pixels); camera intrinsics fx, fy, cx, cy.
* level:  vehicle-heading frame, levelled: forward, right, down.
* NED:    north, east, down.

With a stabilised gimbal the camera's roll/pitch are earth-referenced, so only the
vehicle heading (plus gimbal yaw) is needed. Calibrated in SITL+Gazebo: at nadir the top
of the image is vehicle-forward and the right edge is vehicle-right (see EXPERIMENTS.md,
"projection calibration").
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from backends.base import CameraModel, Telemetry
from common.geo import offset


@dataclass(frozen=True)
class GroundPoint:
    lat: float
    lon: float
    north_m: float  # offset from the vehicle
    east_m: float
    range_m: float


def ray_level(u: float, v: float, cam: CameraModel, gimbal_pitch_deg: float) -> np.ndarray:
    """Unit-free ray (forward, right, down) for a pixel, gimbal pitched by ``gimbal_pitch_deg``
    (-90 = straight down, 0 = horizon)."""
    p = math.radians(gimbal_pitch_deg)
    xr = (u - cam.cx) / cam.fx
    yd = (v - cam.cy) / cam.fy
    optical = np.array([math.cos(p), 0.0, -math.sin(p)])
    img_down = np.array([math.sin(p), 0.0, math.cos(p)])
    img_right = np.array([0.0, 1.0, 0.0])
    return xr * img_right + yd * img_down + optical


def pixel_to_ground(
    u: float,
    v: float,
    cam: CameraModel,
    pose: Telemetry,
    gimbal_pitch_deg: float | None = None,
    gimbal_yaw_deg: float = 0.0,
    ground_alt_rel_m: float = 0.0,
) -> GroundPoint | None:
    """Intersect the pixel's ray with the ground plane. None if it points above the horizon."""
    if pose.lat is None or pose.lon is None or pose.alt_rel_m is None:
        return None
    pitch = -90.0 if gimbal_pitch_deg is None else gimbal_pitch_deg
    r = ray_level(u, v, cam, pitch)
    if r[2] <= 1e-6:
        return None
    h = pose.alt_rel_m - ground_alt_rel_m
    if h <= 0.2:
        return None
    s = h / r[2]
    fwd, right = r[0] * s, r[1] * s
    yaw = pose.yaw_rad + math.radians(gimbal_yaw_deg)
    north = fwd * math.cos(yaw) - right * math.sin(yaw)
    east = fwd * math.sin(yaw) + right * math.cos(yaw)
    lat, lon = offset(pose.lat, pose.lon, north, east)
    return GroundPoint(lat, lon, north, east, float(math.hypot(north, east)))


def ground_sample_distance_m(cam: CameraModel, alt_m: float) -> float:
    """Metres per pixel at the image centre for a nadir camera."""
    return alt_m / cam.fx


def footprint_m(cam: CameraModel, alt_m: float) -> tuple[float, float]:
    """(across-track width, along-track height) of a nadir frame on the ground."""
    return cam.width * alt_m / cam.fx, cam.height * alt_m / cam.fy


def altitude_for_pixels(cam: CameraModel, object_size_m: float, min_pixels: float) -> float:
    """Highest altitude at which an object still spans ``min_pixels`` pixels."""
    return object_size_m * cam.fx / min_pixels
