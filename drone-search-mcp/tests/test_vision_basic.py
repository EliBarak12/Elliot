import numpy as np

from backends.base import CameraModel, Frame, Telemetry
from backends.fake import HOME
from common.geo import distance_m, offset
from vision.matcher import CropScore, guess_object_noun, hist_similarity, hs_hist, object_mask
from vision.pipeline import CandidateTracker, Detection
from vision.proposals import ProposalConfig, crop_square, propose


def grass(h: int = 480, w: int = 640) -> np.ndarray:
    rng = np.random.default_rng(1)
    return (rng.normal(0, 6, (h, w, 3)) + np.array([70, 120, 50])).clip(0, 255).astype(np.uint8)


def test_proposal_finds_coloured_object_and_skips_lines() -> None:
    img = grass()
    img[200:220, 300:320] = (200, 20, 20)  # 20 px object
    img[100:102, 50:600] = (220, 210, 160)  # 2 px painted line
    props = propose(img, gsd_m=0.03)
    assert props, "object not proposed"
    cx, cy = props[0].center
    assert abs(cx - 310) < 6 and abs(cy - 210) < 6
    assert all(p.y1 - p.y0 > 4 for p in props)  # the thin line is not a proposal
    crop, (x0, y0, x1, y1) = crop_square(img, props[0], 2.0)
    assert crop.shape[0] > 20 and x0 <= 300 and x1 >= 320


def test_proposal_size_filter() -> None:
    img = grass()
    img[100:400, 100:500] = (200, 20, 20)  # 12 m object at 3 cm/px: too big
    assert propose(img, gsd_m=0.03) == []


def test_object_mask_and_colour_hist() -> None:
    ref = np.full((100, 100, 3), 200, np.uint8)
    ref[30:70, 30:70] = (200, 20, 20)
    m = object_mask(ref)
    assert m[50, 50] == 1 and m[5, 5] == 0
    red = hs_hist(ref, m)
    other = np.full((40, 40, 3), (20, 40, 200), np.uint8)
    assert hist_similarity(red, hs_hist(ref[30:70, 30:70], None)) > 0.9
    assert hist_similarity(red, hs_hist(other, None)) < 0.3


def test_guess_object_noun() -> None:
    assert guess_object_noun("a blue hatchback car") == "car"
    assert guess_object_noun("a red backpack lying on the ground") == "backpack"
    assert guess_object_noun("lost hiker, woman in red") == "person"
    assert guess_object_noun("something shiny") is None


def _det(n: float, e: float, score: float) -> Detection:
    lat, lon = offset(*HOME, n, e)
    return Detection(
        lat,
        lon,
        score,
        CropScore(score, score, None, None, 1.0),
        (0, 0, 1, 1),
        0.5,
        1,
        20,
        np.zeros((4, 4, 3), np.uint8),
    )


def test_tracker_merges_nearby_and_ranks() -> None:
    t = CandidateTracker(merge_radius_m=3)
    t.add([_det(10, 10, 0.6), _det(40, 0, 0.9)])
    t.add([_det(11, 10.5, 0.7)])
    t.add([_det(10.5, 9.5, 0.65)])
    assert len(t.candidates) == 2
    a = next(c for c in t.candidates.values() if c.n_obs == 3)
    lat, lon = offset(*HOME, 10.5, 10)
    assert distance_m(a.lat, a.lon, lat, lon) < 1.0
    assert a.best_score == 0.7
    assert a.position_spread_m < 1.5
    ranked = t.ranked()
    assert ranked[0].confidence >= ranked[1].confidence
    cam = CameraModel(640, 480, 500, 500, 320, 240)
    f = Frame(
        np.zeros((480, 640, 3), np.uint8),
        cam,
        1,
        0.0,
        0.0,
        Telemetry(lat=HOME[0], lon=HOME[1], alt_rel_m=30, yaw_rad=0.0),
    )
    t.note_coverage(f)
    assert a.n_frames_covered == 1  # 10 m away: inside a 38 x 29 m footprint
    assert next(c for c in t.candidates.values() if c.n_obs == 1).n_frames_covered == 0


def test_tracker_one_observation_per_frame() -> None:
    t = CandidateTracker(merge_radius_m=3)
    # object + its shadow, 1.5 m apart, in the same frame: one observation, best score kept
    t.add([_det(0, 20, 0.5), _det(0, 21.5, 0.8)])
    assert len(t.candidates) == 1
    c = next(iter(t.candidates.values()))
    assert c.n_obs == 1 and c.best_score == 0.8


def test_shadow_is_not_part_of_the_object() -> None:
    img = grass()
    img[200:220, 300:320] = (230, 230, 230)  # 0.6 m white object at 3 cm/px
    img[215:235, 260:305] = (img[215:235, 260:305] * 0.45).astype(np.uint8)  # cast shadow, same hue
    p = propose(img, gsd_m=0.03)[0]
    assert p.size_px * 0.03 < 0.9, "shadow merged into the blob"
    assert propose(img, gsd_m=0.03, cfg=ProposalConfig(suppress_shadows=False))[0].size_px * 0.03 > 1.2


def test_tall_objects_expected_larger_off_nadir() -> None:
    from vision.matcher import TargetSpec

    t = TargetSpec(
        "a person", "a person", None, 0.5, False, np.zeros((1, 2)), np.zeros((1, 2)), None, None, None, height_m=1.75
    )
    assert t.expected_size_m(0.0) == 0.5
    assert t.expected_size_m(0.6) == 0.5 + 1.75 * 0.6
