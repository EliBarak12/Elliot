import pytest
from shapely.geometry import Point, Polygon

from backends.base import CameraModel
from common.geo import ne_between, offset
from server.planner import EnergyModel, circle_polygon, lawnmower, make_plan, spiral

CAM = CameraModel(1280, 960, 935.49, 935.49, 640, 480)
HOME = (47.397742, 8.545594)


def square(side: float, cn: float = 0, ce: float = 0) -> list[tuple[float, float]]:
    h = side / 2
    return [offset(*HOME, cn + n, ce + e) for n, e in ((-h, -h), (-h, h), (h, h), (h, -h))]


def test_lawnmower_lanes_cover_area() -> None:
    area = Polygon([(0, 0), (100, 0), (100, 60), (0, 60)])
    pts = lawnmower(area, 20.0)
    ys = sorted({round(p[1], 3) for p in pts})
    assert len(ys) == 3  # 60 m / 20 m lanes, along the long (x) axis
    assert ys[0] == pytest.approx(10.0) and ys[-1] == pytest.approx(50.0)
    assert all(area.buffer(1.5).contains(Point(p)) for p in pts)


def test_spiral_starts_at_centre() -> None:
    area = Polygon([(0, 0), (60, 0), (60, 60), (0, 60)])
    pts = spiral(area, 15.0)
    assert pts[0] == pytest.approx((30.0, 30.0))
    assert len(pts) > 4


def test_plan_altitude_from_target_size() -> None:
    p = make_plan(square(80), CAM, 0.5, None, 0.3, "lawnmower", 6.0, HOME, HOME, EnergyModel())
    assert p.altitude_m == pytest.approx(0.5 * 935.49 / 22, abs=0.1)
    assert p.target_px == pytest.approx(22, abs=0.5)
    assert p.lane_spacing_m == pytest.approx(p.footprint_m[0] * 0.7)
    assert p.est_time_s > p.path_length_m / 6.0
    assert p.est_battery_pct > 0
    assert not p.warnings


def test_plan_altitude_clamped_and_warns_small_target() -> None:
    p = make_plan(square(60), CAM, 4.2, None, 0.3, "lawnmower", 6.0, HOME, HOME, EnergyModel())
    assert p.altitude_m == 40.0
    q = make_plan(square(60), CAM, 0.2, 40.0, 0.3, "lawnmower", 6.0, HOME, HOME, EnergyModel())
    assert any("px" in w for w in q.warnings)


def test_plan_without_target_warns() -> None:
    p = make_plan(square(60), CAM, None, None, 0.05, "spiral", 6.0, HOME, HOME, EnergyModel())
    assert p.altitude_m == 25.0
    assert len(p.warnings) == 2


def test_degenerate_polygon_rejected() -> None:
    with pytest.raises(ValueError):
        make_plan([HOME, HOME, HOME], CAM, 0.5, None, 0.3, "lawnmower", 6.0, HOME, HOME, EnergyModel())


def test_circle_polygon_radius() -> None:
    for la, lo in circle_polygon(*HOME, 30):
        n, e = ne_between(*HOME, la, lo)
        assert (n * n + e * e) ** 0.5 == pytest.approx(30, abs=1e-6)


def test_energy_model_learns_rate() -> None:
    m = EnergyModel()
    for i in range(200):
        m.observe(float(i), 100 - i * 0.2, airborne=True)  # 12 %/min
    assert m.pct_per_min_cruise == pytest.approx(12.0, abs=0.01)
    m.observe(500.0, None, airborne=True)
    m.observe(501.0, 10.0, airborne=False)
    assert len(m.samples) == 200
