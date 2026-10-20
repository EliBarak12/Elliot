import math

import pytest

from backends.base import CameraModel, Telemetry
from common.geo import bearing_deg, distance_m, ne_between, offset
from vision.projection import altitude_for_pixels, footprint_m, ground_sample_distance_m, pixel_to_ground

CAM = CameraModel(1280, 960, 935.49, 935.49, 640, 480)
HOME = (47.397742, 8.545594)


def pose(alt: float = 25.0, yaw_deg: float = 0.0, lat: float = HOME[0], lon: float = HOME[1]) -> Telemetry:
    return Telemetry(lat=lat, lon=lon, alt_rel_m=alt, yaw_rad=math.radians(yaw_deg))


def test_offset_roundtrip() -> None:
    lat, lon = offset(*HOME, 20.0, -35.0)
    n, e = ne_between(*HOME, lat, lon)
    assert n == pytest.approx(20.0, abs=1e-6)
    assert e == pytest.approx(-35.0, abs=1e-6)
    assert distance_m(*HOME, lat, lon) == pytest.approx(math.hypot(20, 35), abs=1e-6)
    assert bearing_deg(*HOME, *offset(*HOME, 0, 10)) == pytest.approx(90.0)


def test_centre_pixel_is_below_drone() -> None:
    g = pixel_to_ground(640, 480, CAM, pose())
    assert g is not None
    assert g.range_m == pytest.approx(0.0, abs=1e-6)


def test_matches_gazebo_calibration() -> None:
    # Calibration flight: a marker 10 m east of the drone at 25 m appeared 374 px right of centre.
    g = pixel_to_ground(640 + 374, 480, CAM, pose())
    assert g is not None
    assert g.east_m == pytest.approx(10.0, abs=0.05)
    assert g.north_m == pytest.approx(0.0, abs=1e-6)


def test_image_top_is_heading() -> None:
    # heading east: the top of the image looks east
    g = pixel_to_ground(640, 480 - 374, CAM, pose(yaw_deg=90))
    assert g is not None
    assert g.east_m == pytest.approx(10.0, abs=0.05)
    assert abs(g.north_m) < 1e-6


def test_oblique_ray_above_horizon_is_none() -> None:
    assert pixel_to_ground(640, 0, CAM, pose(), gimbal_pitch_deg=0.0) is None


def test_requires_position_and_altitude() -> None:
    assert pixel_to_ground(1, 1, CAM, Telemetry()) is None
    assert pixel_to_ground(1, 1, CAM, pose(alt=0.1)) is None


def test_gsd_footprint_altitude() -> None:
    assert ground_sample_distance_m(CAM, 25) == pytest.approx(25 / 935.49)
    w, h = footprint_m(CAM, 25)
    assert w == pytest.approx(34.2, abs=0.1)
    assert h == pytest.approx(25.65, abs=0.1)
    assert altitude_for_pixels(CAM, 0.5, 20) == pytest.approx(23.39, abs=0.01)
