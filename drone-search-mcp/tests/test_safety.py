import time

import pytest

from backends.fake import HOME, FakeBackend
from common.geo import offset
from server.errors import ActuationDisabled, NotSimulation, SafetyViolation
from server.safety import SafetyConfig, SafetyGate, point_in_polygon


@pytest.fixture
def backend() -> FakeBackend:
    b = FakeBackend(speedup=50)
    b.connect()
    yield b
    b.close()


def test_actuation_flag_required(backend: FakeBackend) -> None:
    with pytest.raises(ActuationDisabled):
        SafetyGate(SafetyConfig(allow_actuation=False), backend).require_actuation()
    SafetyGate(SafetyConfig(allow_actuation=True), backend).require_actuation()


def test_refuses_non_simulated_vehicle(backend: FakeBackend, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend, "is_simulation", lambda: False)
    with pytest.raises(NotSimulation):
        SafetyGate(SafetyConfig(allow_actuation=True), backend).require_actuation()


def test_geofence_and_altitude(backend: FakeBackend) -> None:
    g = SafetyGate(SafetyConfig(allow_actuation=True, max_radius_m=100), backend)
    g.check_point(*offset(*HOME, 50, 0), 20)
    with pytest.raises(SafetyViolation, match="geofence"):
        g.check_point(*offset(*HOME, 150, 0), 20)
    with pytest.raises(SafetyViolation, match="altitude"):
        g.check_point(*HOME, 100)
    with pytest.raises(SafetyViolation, match="altitude"):
        g.check_point(*HOME, 2)
    with pytest.raises(SafetyViolation, match="out of range"):
        g.check_point(95.0, 0.0, 20)


def test_polygon_fence(backend: FakeBackend) -> None:
    poly = [offset(*HOME, n, e) for n, e in ((-20, -20), (-20, 20), (20, 20), (20, -20))]
    assert point_in_polygon(*HOME, poly)
    g = SafetyGate(SafetyConfig(allow_actuation=True, fence_polygon=poly), backend)
    with pytest.raises(SafetyViolation, match="polygon"):
        g.check_point(*offset(*HOME, 30, 0), 20)


def test_battery_budget(backend: FakeBackend) -> None:
    g = SafetyGate(SafetyConfig(), backend)
    g.check_battery_for(60)
    with pytest.raises(SafetyViolation, match="reserve"):
        g.check_battery_for(75)


def test_unknown_home_fails_closed(backend: FakeBackend) -> None:
    backend._t.home_lat = None
    g = SafetyGate(SafetyConfig(), backend)
    g.home_wait_s = 0.5
    with pytest.raises(SafetyViolation, match="home"):
        g.check_point(*HOME, 20)


def test_reserve_monitor_triggers_rtl(backend: FakeBackend) -> None:
    g = SafetyGate(SafetyConfig(allow_actuation=True, battery_reserve_pct=30), backend)
    fired = []
    g.on_reserve(lambda: fired.append(True))
    backend.arm_and_takeoff(10)
    backend._t.alt_rel_m = 10.0
    backend._t.battery_pct = 29.0
    g.start_monitor()
    t0 = time.time()
    while not fired and time.time() - t0 < 5:
        time.sleep(0.05)
    g.stop_monitor()
    assert fired and g.state.reserve_triggered
    assert "mode RTL" in backend.commands
    assert g.describe()["reserve_triggered"] is True
