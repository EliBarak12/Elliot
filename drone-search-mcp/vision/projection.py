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


def undistort(u: float, v: float, cam: CameraModel) -> tuple[float, float]:
    """Normalised, undistorted image coordinates of a (distorted) pixel."""
    xd, yd = (u - cam.cx) / cam.fx, (v - cam.cy) / cam.fy
    if cam.k1 == 0.0 and cam.k2 == 0.0:
        return xd, yd
    xu, yu = xd, yd
    for _ in range(8):
        r2 = xu * xu + yu * yu
        f = 1 + cam.k1 * r2 + cam.k2 * r2 * r2
        xu, yu = xd / f, yd / f
    return xu, yu


def ray_level(u: float, v: float, cam: CameraModel, gimbal_pitch_deg: float) -> np.ndarray:
    """Unit-free ray (forward, right, down) for a pixel, gimbal pitched by ``gimbal_pitch_deg``
    (-90 = straight down, 0 = horizon)."""
    p = math.radians(gimbal_pitch_deg)
    xr, yd = undistort(u, v, cam)
    optical = np.array([math.cos(p), 0.0, -math.sin(p)])
    img_down = np.array([math.sin(p), 0.0, math.cos(p)])
    img_right = np.array([0.0, 1.0, 0.0])
    return xr * img_right + yd * img_down + optical


def _quat_matrix(q: tuple[float, float, float, float]) -> np.ndarray:
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def _euler_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """Body FRD -> NED (aerospace ZYX)."""
    cr, sr, cp, sp, cy, sy = (
        math.cos(roll),
        math.sin(roll),
        math.cos(pitch),
        math.sin(pitch),
        math.cos(yaw),
        math.sin(yaw),
    )
    return np.array(
        [
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr],
        ]
    )


def pixel_ray_ned(
    u: float,
    v: float,
    cam: CameraModel,
    pose: Telemetry,
    gimbal_pitch_deg: float | None = None,
    gimbal_yaw_deg: float = 0.0,
) -> np.ndarray:
    """Ray direction (north, east, down) through a pixel.

    Preferred: full camera attitude = body attitude (EKF) x gimbal attitude relative to the
    body (as the gimbal reports it). The camera looks along the gimbal's forward axis with
    image-right = gimbal right and image-down = gimbal down (calibrated in Gazebo: at nadir
    the image top is vehicle-forward). Fallback when the gimbal reports nothing: assume an
    earth-stabilised camera at ``gimbal_pitch_deg`` (default nadir), yawed with the vehicle.
    """
    xr, yd = undistort(u, v, cam)
    if pose.gimbal_earth_locked and pose.gimbal_target_pitch_deg is not None:
        # Earth-stabilised gimbal (ArduPilot servo mount in MAVLink targeting): roll 0 and
        # the commanded pitch in the earth frame, yaw with the vehicle. Its reported attitude
        # quaternion cannot be used here: at -90 deg pitch roll and yaw are degenerate in
        # the Euler angles it is built from, and the airframe's roll leaks in (1.8 m at 20 m
        # with 4.8 deg of wind roll, self-play session 2).
        gimbal_pitch_deg = pose.gimbal_target_pitch_deg
    elif pose.gimbal_q_body is not None:
        r_cam = _euler_matrix(pose.roll_rad, pose.pitch_rad, pose.yaw_rad) @ _quat_matrix(pose.gimbal_q_body)
        return r_cam @ np.array([1.0, xr, yd])
    r = ray_level(u, v, cam, -90.0 if gimbal_pitch_deg is None else gimbal_pitch_deg)
    yaw = pose.yaw_rad + math.radians(gimbal_yaw_deg)
    fwd, right, down = r
    return np.array([fwd * math.cos(yaw) - right * math.sin(yaw), fwd * math.sin(yaw) + right * math.cos(yaw), down])


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
    ray = pixel_ray_ned(u, v, cam, pose, gimbal_pitch_deg, gimbal_yaw_deg)
    if ray[2] <= 1e-6:
        return None
    h = pose.alt_rel_m - ground_alt_rel_m
    if h <= 0.2:
        return None
    s = h / ray[2]
    north, east = float(ray[0] * s), float(ray[1] * s)
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
