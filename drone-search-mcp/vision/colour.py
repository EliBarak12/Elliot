"""Measured object colour, so look-alikes that differ only in tint can be told apart.

An agent looking at a dim, compressed close-up reported a beige box as "a white box" twice
(hard-7011, hard-7017). In CIELAB the two differ clearly (white box b* ~2, beige box b* ~10
on the field; reference white box b* ~1), so the server measures it instead of leaving it to
the eye.

Objects are often multi-coloured (a red backpack with a black front panel: a single median
read its reference as "black", medium-8001), so each object is summarised as a small
palette and every close-up colour is matched to the nearest reference colour.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
import structlog

from vision.matcher import object_mask

log = structlog.get_logger(__name__)

# CIELAB hue angle upper bounds (degrees); saturated reds sit at ~30 deg in Lab
HUES = [(45, "red"), (75, "orange/tan"), (105, "yellow/beige"), (190, "green"), (310, "blue"), (340, "purple")]


def _lab(img: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    return lab[..., 0] * 100 / 255, lab[..., 1] - 128, lab[..., 2] - 128


Palette = list[dict[str, float]]  # [{"L", "a", "b", "share"}], largest share first

# lightness counts a little (white vs black are both colourless), tint counts fully
L_WEIGHT = 0.2
# a reference colour at least this saturated identifies the object (red, blue, ...) and must
# appear in the close-up
KEY_CHROMA = 20.0  # jeans measure ~12 (barely visible from above), a blue car ~32, red ~46


def _palette(L: np.ndarray, a: np.ndarray, b: np.ndarray, keep: np.ndarray, k: int = 3) -> Palette | None:
    """Main colours of the masked pixels (k-means in CIELAB, clusters under 12% dropped)."""
    n = int(keep.sum())
    if n < 20:
        return None
    px = np.stack([L[keep], a[keep], b[keep]], axis=1).astype(np.float32)
    if n > 5000:
        px = px[np.random.default_rng(0).choice(n, 5000, replace=False)]
    k = min(k, len(px))
    _, labels, centers = cv2.kmeans(
        px,
        k,
        np.zeros((len(px), 1), np.int32),
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5),
        3,
        cv2.KMEANS_PP_CENTERS,
    )
    shares = np.bincount(np.asarray(labels, np.int64).ravel(), minlength=k) / len(px)
    out = [
        {"L": float(c[0]), "a": float(c[1]), "b": float(c[2]), "share": float(sh)}
        for c, sh in zip(centers, shares, strict=True)
        if sh >= 0.12
    ]
    total = sum(c["share"] for c in out)
    for c in out:
        c["share"] /= total
    return sorted(out, key=lambda c: -c["share"])


def reference_colour(ref: np.ndarray) -> Palette | None:
    """Main CIELAB colours (L 0-100, a, b) of the object in a reference photo."""
    if ref.size == 0 or min(ref.shape[:2]) < 8:
        return None
    L, a, b = _lab(ref)
    return _palette(L, a, b, object_mask(ref).astype(bool))


def closeup_colour(img: np.ndarray) -> Palette | None:
    """Main CIELAB colours of the central object in a top-down close-up.

    The background is the ground around it (the crop border). Shadows - darker versions of
    the ground colour, which join a box's outline from above - and edge pixels blended with
    the ground are left out, or a white box would read as grey-green.
    """
    if img.size == 0 or min(img.shape[:2]) < 16:
        return None
    L, a, b = _lab(img)
    h, w = L.shape
    bw = max(2, min(h, w) // 16)
    border = np.zeros((h, w), bool)
    border[:bw], border[-bw:], border[:, :bw], border[:, -bw:] = True, True, True, True
    gL, ga, gb = (float(np.median(x[border])) for x in (L, a, b))
    dist = np.sqrt((L - gL) ** 2 + (a - ga) ** 2 + (b - gb) ** 2)
    r = np.clip(L / max(gL, 1.0), 0.0, 1.0)
    shadow = (0.85 * gL > L) & (np.hypot(a - ga * r, b - gb * r) < 8)
    fg = cv2.erode(((dist > 15) & ~shadow).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=2)
    n, labels, stats, cent = cv2.connectedComponentsWithStats(fg)
    if n <= 1:
        return None
    best = max(
        range(1, n),
        key=lambda i: stats[i, 4] / (1 + math.hypot(cent[i][0] - w / 2, cent[i][1] - h / 2) / max(h, w) * 4),
    )
    return _palette(L, a, b, labels == best)


def colour_name(c: dict[str, float]) -> str:
    chroma = math.hypot(c["a"], c["b"])
    if chroma < 6:
        return "white/light grey" if c["L"] > 60 else ("grey" if c["L"] > 30 else "black/dark grey")
    hue = math.degrees(math.atan2(c["b"], c["a"])) % 360
    name = next((n for h, n in HUES if hue < h), "pink/red")
    return f"pale {name}" if chroma < 15 and c["L"] > 60 else name


def _distance(c: dict[str, float], r: dict[str, float]) -> float:
    """Colour distance relative to the reference colour's saturation: sunlight and shading
    shift a saturated red by far more (in absolute units) than a white, and a red target
    measured 6.7 from its reference while white objects measure ~2 from theirs."""
    d = math.sqrt((c["a"] - r["a"]) ** 2 + (c["b"] - r["b"]) ** 2 + (L_WEIGHT * (c["L"] - r["L"])) ** 2)
    return d / (math.hypot(r["a"], r["b"]) + 10.0)


def _describe(p: Palette) -> str:
    return ", ".join(f"{colour_name(c)} {round(100 * c['share'])}%" for c in p)


def compare(closeup: Palette | None, reference: Palette | None) -> dict[str, object] | None:
    """How far the close-up's colours are from the nearest reference colours (share-weighted;
    mostly tint, so lighting level matters little), with a plain verdict."""
    if not closeup or not reference:
        return None
    d = sum(c["share"] * min(_distance(c, r) for r in reference) for c in closeup)
    # The reference's own colour must show up in the close-up. Neutral parts (tyres, windows,
    # straps) are common to many objects: a white car matched a blue car's grey windows and
    # read as "same colours" (hard-8002).
    missing = [
        r
        for r in reference
        if r["share"] >= 0.25
        and math.hypot(r["a"], r["b"]) >= KEY_CHROMA
        and not any(c["share"] >= 0.15 and _distance(c, r) < 0.45 for c in closeup)
    ]
    # v5/v6 close-ups: white objects 0.11-0.25 from a white reference, beige boxes 0.75-0.95,
    # red backpacks 0.11-0.39 from a red one, red vs white ~4
    if missing:
        verdict = (
            f"clearly different colours from the reference: its {colour_name(missing[0])} is missing from the "
            "close-up; likely a look-alike"
        )
    elif d < 0.45:
        verdict = "same colours as the reference"
    elif d < 0.65:
        verdict = "slightly different colours from the reference (check it is not a look-alike)"
    else:
        verdict = "clearly different colours from the reference (e.g. beige vs white): likely a look-alike"
    return {
        "closeup_object": _describe(closeup),
        "reference_object": _describe(reference),
        "colour_difference": round(d, 2),
        "verdict": verdict,
        "note": "Measured on the central object (shadows excluded); lighting differs between the photos.",
    }
