import numpy as np

from vision.colour import closeup_colour, colour_name, compare, reference_colour

GRASS = (60, 100, 40)


def _aerial(rgb: tuple[int, int, int]) -> np.ndarray:
    """Top-down crop: a box on grass with a darker-grass shadow joined to one side."""
    img = np.zeros((240, 240, 3), np.uint8)
    img[:] = GRASS
    img[110:190, 110:190] = (30, 52, 22)  # shadow: same hue as the grass, darker
    img[80:160, 80:160] = rgb
    noise = np.random.default_rng(0).normal(0, 3, img.shape)
    return np.clip(img + noise, 0, 255).astype(np.uint8)


def _reference(rgb: tuple[int, int, int]) -> np.ndarray:
    """Studio photo: grey floor, white sky band at the top, the object in the middle."""
    img = np.full((240, 320, 3), 190, np.uint8)
    img[:30] = 250
    img[90:170, 120:220] = rgb
    return img


def test_beige_box_reads_as_a_different_tint_from_a_white_reference() -> None:
    # hard-7011 / hard-7017: the agent reported a beige box as "a white box"
    ref = reference_colour(_reference((235, 235, 232)))
    beige = closeup_colour(_aerial((200, 190, 160)))
    white = closeup_colour(_aerial((200, 200, 198)))
    assert beige is not None and white is not None and ref is not None
    assert "beige" in colour_name(beige) and colour_name(white) == "white/light grey"
    far, near = compare(beige, ref), compare(white, ref)
    assert far is not None and near is not None
    assert str(far["verdict"]).startswith("clearly different") and float(far["tint_difference"]) >= 7  # type: ignore[arg-type]
    assert near["verdict"] == "same tint as the reference"


def test_shadow_is_not_measured_as_the_object() -> None:
    c = closeup_colour(_aerial((200, 200, 198)))
    assert c is not None and c["L"] > 70  # the box, not its dark shadow


def test_colour_names() -> None:
    assert colour_name({"L": 40, "a": 42, "b": 23}) == "red"  # the red backpack in v5 close-ups
    assert colour_name({"L": 27, "a": 2, "b": -25}) == "blue"
    assert colour_name({"L": 20, "a": 0, "b": 1}) == "black/dark grey"


def test_degenerate_inputs_give_no_measurement() -> None:
    assert closeup_colour(np.zeros((8, 8, 3), np.uint8)) is None
    flat = np.full((120, 120, 3), GRASS, np.uint8)
    assert closeup_colour(flat) is None  # nothing but ground
    assert reference_colour(np.zeros((4, 4, 3), np.uint8)) is None
    assert compare(None, {"L": 50, "a": 0, "b": 0}) is None
    assert compare({"L": 50, "a": 0, "b": 0}, None) is None


def test_slightly_different_band() -> None:
    r = compare({"L": 60, "a": 0, "b": 6}, {"L": 70, "a": 0, "b": 1})
    assert r is not None and str(r["verdict"]).startswith("slightly")
