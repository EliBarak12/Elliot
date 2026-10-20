import math
import time

from backends.ardupilot import POSITION_ONLY_MASK, POSITION_YAW_MASK
from backends.fake import HOME, FakeBackend
from common.geo import offset
from server.mission import MissionRunner
from server.planner import EnergyModel
from server.recorder import FlightRecorder


def test_yaw_mask_uses_yaw_but_still_ignores_velocity_and_yaw_rate() -> None:
    assert POSITION_ONLY_MASK & 0x400 and not POSITION_YAW_MASK & 0x400
    assert POSITION_YAW_MASK | 0x400 == POSITION_ONLY_MASK  # only the yaw bit differs


def test_inspection_moves_keep_the_heading(tmp_path) -> None:
    # Turning to face each short re-centring move spun the camera, and the analyzer skipped
    # the frames as unsteady (hard-7011).
    b = FakeBackend([], speedup=30)
    b.connect()
    try:
        runner = MissionRunner(b, FlightRecorder(b, tmp_path, enabled=False), EnergyModel())
        runner.ensure_airborne(12.0)
        runner.fly_to(*offset(*HOME, 10, 0), 12.0, 5.0, tol_m=0.5)  # now facing north
        heading = b.telemetry().heading_deg
        runner.fly_to(*offset(*HOME, 10, 5), 12.0, 2.0, tol_m=0.3, hold_heading=True)  # move east
        assert heading is not None
        assert abs(b.telemetry().heading_deg - heading) < 1.0  # type: ignore[operator]
        runner.fly_to(*offset(*HOME, 10, 10), 12.0, 2.0, tol_m=0.3)  # default: face the travel
        assert abs(math.radians(b.telemetry().heading_deg) - math.pi / 2) < 0.05  # type: ignore[arg-type]
    finally:
        b.close()


def test_steady_frame_waits_out_rotation(tmp_path) -> None:
    b = FakeBackend([], speedup=30)
    b.connect()
    try:
        runner = MissionRunner(b, FlightRecorder(b, tmp_path, enabled=False), EnergyModel())
        runner.ensure_airborne(12.0)
        b._t.yaw_rate = math.radians(40)  # spinning
        assert runner._steady_frame(0.6, 3.0).pose.tilt_rate_dps > 3.0  # falls back to the last frame
        b._t.yaw_rate = 0.0
        t0 = time.time()
        f = runner._steady_frame(3.0, 3.0)
        assert f is not None and f.pose.tilt_rate_dps <= 3.0 and time.time() - t0 < 3.0
    finally:
        b.close()
