import math

import pytest

from backends.base import CameraModel, Telemetry
from common.geo import bearing_deg, distance_m, ne_between, offset
from vision.projection import altitude_for_pixels, footprint_m, ground_sample_distance_m, pixel_to_ground, undistort

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


def test_undistort_inverts_simulated_lens() -> None:
    import numpy as np

    from sim.realism import TRUE_K1, TRUE_K2, Degrader, RealismProfile

    d = Degrader(RealismProfile(), 1280, 960, CAM.fx)
    cam = CameraModel(1280, 960, CAM.fx, CAM.fy, 640, 480, TRUE_K1, TRUE_K2)
    # output pixel (u, v) shows ideal pixel (map_x, map_y); undistorting (u, v) must land there
    for u, v in ((1200, 900), (100, 80), (640, 100), (900, 480)):
        xu, yu = undistort(u, v, cam)
        assert xu * CAM.fx + 640 == pytest.approx(float(d.map_x[v, u]), abs=0.05)
        assert yu * CAM.fy + 480 == pytest.approx(float(d.map_y[v, u]), abs=0.05)
    assert np.all(d.vignette <= 1.0)


def test_degrader_outputs_jpeg() -> None:
    import io

    import numpy as np
    from PIL import Image

    from sim.realism import Degrader, RealismProfile

    rgb = np.full((96, 128, 3), 120, np.uint8)
    out = Degrader(RealismProfile(), 128, 96, 100.0).apply(rgb, (300.0, 0.0), 20.0)
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG" and img.size == (128, 96)


def _q_pitch(deg: float) -> tuple[float, float, float, float]:
    a = math.radians(deg) / 2
    return (math.cos(a), 0.0, math.sin(a), 0.0)


def test_body_relative_gimbal_composes_with_attitude() -> None:
    # level airframe, gimbal -90 relative: plain nadir, same as the fallback
    p = Telemetry(lat=HOME[0], lon=HOME[1], alt_rel_m=25.0, gimbal_q_body=_q_pitch(-90))
    g = pixel_to_ground(640 + 374, 480, CAM, p)
    assert g is not None and g.east_m == pytest.approx(10.0, abs=0.05) and abs(g.north_m) < 1e-6
    # cruising nose-down 25 deg; the stabilised gimbal reports -65 relative -> still nadir
    p2 = Telemetry(lat=HOME[0], lon=HOME[1], alt_rel_m=25.0, pitch_rad=math.radians(-25), gimbal_q_body=_q_pitch(-65))
    g2 = pixel_to_ground(640, 480, CAM, p2)
    assert g2 is not None and g2.range_m == pytest.approx(0.0, abs=1e-6)
    # treating the -65 report as earth-frame (the old bug) would be ~11.7 m off
    g3 = pixel_to_ground(640, 480, CAM, pose(), gimbal_pitch_deg=-65)
    assert g3 is not None and g3.north_m == pytest.approx(25 / math.tan(math.radians(65)), abs=0.05)
