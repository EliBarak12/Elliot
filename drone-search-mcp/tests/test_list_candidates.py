import asyncio
import json

import numpy as np
import pytest
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


def test_lookalike_note_names_matching_closeups_and_uninspected_candidates(tmp_path) -> None:
    # hard-8011: three red close-ups all matched the reference's colours; the agent reported
    # one by shape and never inspected the real target, ranked 7th
    srv = DroneSearchServer(FakeBackend([]), SafetyConfig(allow_actuation=True), tmp_path / "out", record=False)
    for i in range(1, 8):
        c = _cand(i)
        srv.tracker.candidates[c.id] = c
    same = {"colour_check": {"verdict": "same colours as the reference"}}
    inspections = [{"candidate_id": "c1", **same}, {"candidate_id": "c2", **same}, {"candidate_id": "c3"}]
    note = srv._lookalike_note(inspections)
    assert note is not None
    assert note["same_colours_as_reference"] == ["c1", "c2"] and "2 of 3" in note["message"]
    assert note["not_inspected"] == ["c4", "c5", "c6", "c7"]
    # one match is no evidence of look-alikes
    assert srv._lookalike_note(inspections[1:]) is None


def _scene(obj: tuple[int, int, int] | None, ground: tuple[int, int, int]) -> np.ndarray:
    img = np.zeros((200, 200, 3), np.uint8)
    img[:] = ground
    if obj is not None:
        img[70:130, 70:130] = obj
    return np.clip(img + np.random.default_rng(1).normal(0, 3, img.shape), 0, 255).astype(np.uint8)


@pytest.mark.parametrize("closeup_kind", ["trunk", "all_canopy"])
def test_inspection_attaches_search_view_when_canopy_hides_the_object(tmp_path, monkeypatch, closeup_kind) -> None:
    # hard-8014: the target was inspected, but straight down it was under leaves; the agent
    # called it foliage. The search had seen it from an angle with the right colours.
    from vision.colour import reference_colour
    from vision.matcher import build_target

    b = FakeBackend([], speedup=30)
    b.connect()
    (tmp_path / "out").mkdir()
    srv = DroneSearchServer(b, SafetyConfig(allow_actuation=True), tmp_path / "out", record=False)
    srv.target = build_target("a red backpack", None, 0.6)
    ref = np.full((240, 320, 3), 190, np.uint8)
    ref[90:170, 120:220] = (180, 30, 30)
    srv.ref_colour = reference_colour(ref)
    c = _cand(1)
    c.best_crop = _scene((175, 35, 30), (60, 100, 40))  # search pass: red object on grass
    # leaves with a grey trunk (colours clearly differ), or nothing but leaves (no colour measurable, hard-9014)
    canopy = _scene((70, 70, 68) if closeup_kind == "trunk" else None, (35, 50, 25))

    def fake_inspect(cand, analyzer, search_alt, alt, out_dir):  # type: ignore[no-untyped-def]
        return {
            "closeup": canopy, "full_frame": canopy, "object_in_final_frame": True, "closeup_path": "x.jpg",
            "frame_path": "y.jpg", "lat": cand.lat, "lon": cand.lon, "refined_shift_m": 0.0, "redetected": True,
            "closeup_score": 0.3, "alt_m": 12.0, "zoom": 4.0, "cues": None,
        }  # fmt: skip

    monkeypatch.setattr(srv.runner, "run_inspect", fake_inspect)
    try:
        payload, images = srv._inspect(c, None)
    finally:
        b.close()
    if closeup_kind == "trunk":
        assert payload["colour_check"]["verdict"].startswith("clearly different")
    else:
        assert "colour_check" not in payload
    assert payload["search_view"]["colour_check"]["verdict"] == "same colours as the reference"
    assert len(images) == len(payload["images"]) == 2 and "search view" in payload["images"][1]
