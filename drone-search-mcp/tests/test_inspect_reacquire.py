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
        assert res["zoom"] > 1.5 and b.zoom == 1.0  # zoomed for the close-up, then reset
    finally:
        b.close()


@pytest.mark.slow
def test_execute_search_with_inspections_end_to_end(tmp_path) -> None:
    import asyncio
    import json

    from fastmcp import Client
    from PIL import Image

    from server.app import DroneSearchServer, build_mcp
    from server.safety import SafetyConfig

    b = FakeBackend([FakeObject(25, 15, 0.6, (200, 20, 20)), FakeObject(-20, -10, 0.6, (20, 40, 200))], speedup=30)
    ref = np.full((200, 200, 3), 200, np.uint8)
    ref[60:140, 60:140] = (200, 20, 20)
    Image.fromarray(ref).save(tmp_path / "ref.png")
    srv = DroneSearchServer(b, SafetyConfig(allow_actuation=True), tmp_path / "out", record=False)

    async def run() -> None:
        async with Client(build_mcp(srv)) as c:
            await c.call_tool("set_search_target", {"image_path": str(tmp_path / "ref.png"), "text": "a red box"})
            r = await c.call_tool("plan_search", {"center_lat": HOME[0], "center_lon": HOME[1], "radius_m": 40})
            pid = json.loads(r.content[0].text)["plan"]["plan_id"]
            r = await c.call_tool("execute_search", {"plan_id": pid, "inspect_top": 1})
            body = json.loads(r.content[0].text)
            assert len(body["inspections"]) == 1
            ins = body["inspections"][0]
            assert ins["object_in_closeup"] and ins["zoom"] > 1.5
            assert distance_m(ins["lat"], ins["lon"], *offset(*HOME, 25, 15)) < 1.0
            images = [x for x in r.content if x.type == "image"]
            assert len(images) == len(body["candidates"]) + 1  # thumbnails + one composite close-up
            # every attached image is named, in order, so the agent need not guess (hard-7002)
            assert len(body["images"]) == len(images)
            assert body["images"][0] == f"{body['candidates'][0]['candidate_id']} thumbnail"
            assert body["images"][-1] == f"{ins['candidate_id']} close-up beside reference"
            r = await c.call_tool("report_finding", {"candidate_id": ins["candidate_id"], "confidence": 0.9})
            assert json.loads(r.content[0].text)["total_findings"] == 1

    asyncio.run(run())
