"""Measured object colour, so look-alikes that differ only in tint can be told apart.

An agent looking at a dim, compressed close-up reported a beige box as "a white box" twice
(hard-7011, hard-7017). In CIELAB the two differ clearly (white box b* ~2, beige box b* ~10
on the field; reference white box b* ~1), so the server measures it instead of leaving it to
the eye.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
import structlog

from vision.matcher import object_mask

log = structlog.get_logger(__name__)

# CIELAB hue angle upper bounds (degrees); saturated reds sit at ~30 deg in Lab
HUES = [(45, "red"), (75, "orange/tan"), (105, "yellow/beige"), (190, "green"), (290, "blue"), (340, "purple")]


def _lab(img: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    return lab[..., 0] * 100 / 255, lab[..., 1] - 128, lab[..., 2] - 128


def _median(L: np.ndarray, a: np.ndarray, b: np.ndarray, keep: np.ndarray) -> dict[str, float] | None:
    if keep.sum() < 20:
        return None
    return {"L": float(np.median(L[keep])), "a": float(np.median(a[keep])), "b": float(np.median(b[keep]))}


def reference_colour(ref: np.ndarray) -> dict[str, float] | None:
    """Median CIELAB colour (L 0-100, a, b) of the object in a reference photo."""
    if ref.size == 0 or min(ref.shape[:2]) < 8:
        return None
    L, a, b = _lab(ref)
    return _median(L, a, b, object_mask(ref).astype(bool))


def closeup_colour(img: np.ndarray) -> dict[str, float] | None:
    """Median CIELAB colour of the central object in a top-down close-up.

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
    return _median(L, a, b, labels == best)


def colour_name(c: dict[str, float]) -> str:
    chroma = math.hypot(c["a"], c["b"])
    if chroma < 6:
        return "white/light grey" if c["L"] > 60 else ("grey" if c["L"] > 30 else "black/dark grey")
    hue = math.degrees(math.atan2(c["b"], c["a"])) % 360
    name = next((n for h, n in HUES if hue < h), "pink/red")
    return f"pale {name}" if chroma < 15 and c["L"] > 60 else name


def compare(closeup: dict[str, float] | None, reference: dict[str, float] | None) -> dict[str, object] | None:
    """Tint difference (a*/b* distance, lighting-level independent) with a plain verdict."""
    if closeup is None or reference is None:
        return None
    d = math.hypot(closeup["a"] - reference["a"], closeup["b"] - reference["b"])
    # v5 close-ups: white objects measured 1.4-2.2 from a white reference, beige boxes 8.1-10.0
    if d < 4:
        verdict = "same tint as the reference"
    elif d < 7:
        verdict = "slightly different tint from the reference (check it is not a look-alike)"
    else:
        verdict = "clearly different tint from the reference (e.g. beige vs white): likely a look-alike"
    return {
        "closeup_object": colour_name(closeup),
        "reference_object": colour_name(reference),
        "tint_difference": round(d, 1),
        "verdict": verdict,
        "note": "Measured on the central object (shadows excluded); people and multi-coloured objects mix colours.",
    }
