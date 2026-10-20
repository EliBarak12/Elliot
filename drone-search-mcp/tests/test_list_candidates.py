import asyncio
import json

import numpy as np
from fastmcp import Client

from backends.fake import HOME, FakeBackend
from common.geo import offset
from server.app import DroneSearchServer, build_mcp
from server.safety import SafetyConfig
from vision.matcher import CropScore
from vision.pipeline import Candidate


def _cand(i: int) -> Candidate:
    lat, lon = offset(*HOME, 3.0 * i, 0.0)
    crop = np.full((40, 40, 3), 120, np.uint8)
    score = 0.9 - 0.05 * i
    c = Candidate(f"c{i}", lat, lon, score, 4, 4, crop, CropScore(score, 0.5, None, None, 1.0), 0.6, i)
    c.observations = [(lat, lon, score)] * 4
    return c


def test_list_candidates_pages_without_flying(tmp_path) -> None:
    # hard-8008: the agent re-flew the whole search just to see candidates beyond the first six
    b = FakeBackend([], speedup=30)
    srv = DroneSearchServer(b, SafetyConfig(allow_actuation=True), tmp_path / "out", record=False)
    for i in range(1, 9):
        c = _cand(i)
        srv.tracker.candidates[c.id] = c
    srv.tracker.candidates["c2"].status = "rejected"

    async def run() -> None:
        async with Client(build_mcp(srv)) as client:
            r = await client.call_tool("list_candidates", {"offset": 0, "max_candidates": 3})
            body = json.loads(r.content[0].text)
            assert body["n_candidates_total"] == 7  # rejected one left out
            assert [c["candidate_id"] for c in body["candidates"]] == ["c1", "c3", "c4"]
            assert "offset=3" in body["more_candidates"]
            assert len([x for x in r.content if x.type == "image"]) == 3 == len(body["images"])
            r = await client.call_tool("list_candidates", {"offset": 6})
            body = json.loads(r.content[0].text)
            assert [c["candidate_id"] for c in body["candidates"]] == ["c8"] and "more_candidates" not in body

    asyncio.run(run())
    assert b.telemetry().armed is False  # nothing flew


def test_list_candidates_before_any_search(tmp_path) -> None:
    srv = DroneSearchServer(FakeBackend([]), SafetyConfig(allow_actuation=True), tmp_path / "out", record=False)

    async def run() -> None:
        async with Client(build_mcp(srv)) as client:
            body = json.loads((await client.call_tool("list_candidates", {})).content[0].text)
            assert body["candidates"] == [] and "execute_search" in body["next_step"]

    asyncio.run(run())
