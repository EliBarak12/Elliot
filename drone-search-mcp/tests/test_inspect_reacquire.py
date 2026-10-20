import numpy as np
import pytest

from backends.fake import HOME, FakeBackend, FakeObject
from common.geo import distance_m, offset
from server.mission import MissionRunner
from server.planner import EnergyModel
from server.recorder import FlightRecorder
from vision.matcher import CropScore, build_target
from vision.pipeline import Candidate, FrameAnalyzer


@pytest.mark.slow
def test_inspect_reacquires_object_after_gps_drift(tmp_path) -> None:
    # The object is 4 m from where the search said it was (GPS drifted in between).
    b = FakeBackend([FakeObject(30, 20, 0.6, (200, 20, 20))], speedup=30)
    b.connect()
    try:
        runner = MissionRunner(b, FlightRecorder(b, tmp_path, enabled=False), EnergyModel())
        target = build_target("a red box", None, 0.6)
        lat, lon = offset(*HOME, 30 + 3.0, 20 - 2.6)
        cand = Candidate(
            "c1", lat, lon, 0.7, 3, 3, np.zeros((8, 8, 3), np.uint8), CropScore(0.7, 0.7, None, None, 1.0), 0.6, 1
        )
        res = runner.run_inspect(cand, FrameAnalyzer(target), 20.0, 8.0, tmp_path)
        true = offset(*HOME, 30, 20)
        assert res["redetected"] and res["object_in_final_frame"]
        assert distance_m(res["lat"], res["lon"], *true) < 1.0
        assert res["refined_shift_m"] > 3.0
    finally:
        b.close()
