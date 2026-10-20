"""Decide whether an image crop shows the search target.

A target is described by text, a reference photo, or both. Each crop gets three cues:

* text   - CLIP zero-shot: P(target prompt) against background and other-object prompts.
* image  - CLIP embedding similarity to the reference photo (augmented to look aerial).
* colour - hue/saturation histogram similarity between the blob and the reference object.

and a size prior (blob ground size vs the expected object size). Scores are in [0, 1].
When only a photo is given, the text label is inferred from it with CLIP so the text cue
still works; the inferred label is reported back so the agent can correct it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import cv2
import numpy as np
import structlog

from vision import models

log = structlog.get_logger(__name__)

COLORS = ["red", "blue", "white", "black", "grey", "green", "yellow", "orange", "brown", "silver", "purple"]
OBJECTS = {
    # noun: typical largest dimension seen from above (m)
    "backpack": 0.5,
    "car": 4.2,
    "person": 0.6,
    "box": 0.6,
    "suitcase": 0.7,
    "bucket": 0.4,
    "tarp": 3.0,
    "shipping container": 4.0,
    "pickup truck": 5.5,
    "SUV": 4.8,
    "cardboard box": 0.6,
    "bag": 0.5,
    "bicycle": 1.7,
    "barrel": 0.6,
    "mailbox": 0.8,
    "tent": 3.0,
    "dog": 0.8,
}
SYNONYMS = {
    "hatchback": "car",
    "vehicle": "car",
    "van": "car",
    "man": "person",
    "woman": "person",
    "child": "person",
    "people": "person",
    "rucksack": "backpack",
    "pack": "backpack",
    "crate": "box",
    "package": "box",
    "parcel": "box",
    "truck": "pickup truck",
}
# Height above ground (m). Off nadir a tall object is seen partly from the side, so its
# image footprint grows by about height * (ground offset / altitude): a standing person
# 10 m off-centre at 15 m spans ~1.5 m, not their 0.5 m shoulder width (run medium-2001).
HEIGHTS = {
    "backpack": 0.3,
    "car": 1.5,
    "person": 1.75,
    "box": 0.4,
    "suitcase": 0.4,
    "bucket": 0.35,
    "tarp": 0.0,
    "shipping container": 1.4,
    "pickup truck": 1.8,
    "SUV": 1.8,
    "cardboard box": 0.4,
    "bag": 0.3,
    "bicycle": 1.0,
    "barrel": 0.9,
    "mailbox": 1.3,
    "tent": 1.5,
    "dog": 0.6,
}
BACKGROUND_PROMPTS = [
    "grass",
    "a patch of grass",
    "a tree seen from above",
    "a road",
    "asphalt",
    "a shadow on the grass",
    "a house roof",
    "dirt",
    "a road marking",
    "bushes",
]
AERIAL_TEMPLATES = ["an aerial photo of {}", "a drone photo looking down at {}", "a top-down view of {}"]


def guess_object_noun(text: str) -> str | None:
    t = text.lower()
    for noun in sorted(OBJECTS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(noun.lower())}s?\b", t):
            return noun
    for syn, noun in SYNONYMS.items():
        if re.search(rf"\b{syn}s?\b", t):
            return noun
    return None


def object_mask(ref: np.ndarray) -> np.ndarray:
    """Foreground mask of a reference photo. Assumes the object is roughly central and the
    border pixels are background (true for studio shots and most "lost item" photos)."""
    lab = cv2.cvtColor(ref, cv2.COLOR_RGB2LAB).astype(np.float32)
    h, w = lab.shape[:2]
    b = max(2, min(h, w) // 20)
    border = np.concatenate(
        [lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3), lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)]
    )
    bg = np.median(border, axis=0)
    spread = np.median(np.linalg.norm(border - bg, axis=1)) + 1e-3
    dist = np.linalg.norm(lab - bg, axis=2)
    mask = (dist > max(12.0, 4 * spread)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n <= 1:
        m = np.zeros((h, w), np.uint8)
        m[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4] = 1
        return m
    # largest component closest to the centre
    best = max(
        range(1, n),
        key=lambda i: (
            stats[i, 4]
            / (1 + math.hypot(stats[i, 0] + stats[i, 2] / 2 - w / 2, stats[i, 1] + stats[i, 3] / 2 - h / 2) / max(h, w))
        ),
    )
    return (labels == best).astype(np.uint8)


def hs_hist(img: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    # low-saturation pixels carry no reliable hue: give them their own value bins
    hist = cv2.calcHist([hsv], [0, 1], mask, [18, 4], [0, 180, 0, 256]).flatten()
    low_sat = (hsv[..., 1] < 50).astype(np.uint8)
    vh = cv2.calcHist([hsv], [2], low_sat if mask is None else (mask & low_sat), [6], [0, 256]).flatten()
    h = np.concatenate([hist, vh]).astype(np.float32)
    return h / (h.sum() + 1e-6)


def hist_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sum(np.sqrt(a * b)))  # Bhattacharyya coefficient


@dataclass
class TargetSpec:
    text: str | None
    label: str
    inferred_label: str | None
    size_m: float
    has_reference: bool
    text_emb: np.ndarray  # (1, D) mean of positive prompts
    neg_emb: np.ndarray  # (N, D)
    ref_emb: np.ndarray | None  # (K, D)
    ref_hist: np.ndarray | None
    ref_crop: np.ndarray | None
    neg_labels: list[str] = field(default_factory=list)
    height_m: float = 0.3

    def expected_size_m(self, off_nadir_ratio: float) -> float:
        """Expected largest image footprint (m on the ground) at a given ground offset/altitude."""
        return self.size_m + self.height_m * off_nadir_ratio


def infer_label(ref: np.ndarray) -> tuple[str, float]:
    clip = models.clip()
    labels = [f"{c} {o}" for c in COLORS for o in OBJECTS]
    te = clip.texts([f"a photo of a {lbl}" for lbl in labels])
    ie = clip.images([ref])
    logits = clip.logit_scale * ie @ te.T
    p = np.exp(logits - logits.max())
    p /= p.sum()
    i = int(p.argmax())
    return labels[i], float(p[0, i])


def _aerialize(crop: np.ndarray) -> list[np.ndarray]:
    """Reference variants that look more like a 20-40 px aerial view."""
    out = []
    for k in range(4):
        r = np.ascontiguousarray(np.rot90(crop, k))
        for px in (32, 64):
            h, w = r.shape[:2]
            s = px / max(h, w)
            small = cv2.resize(r, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
            out.append(small)
    return out


def build_target(text: str | None, reference: np.ndarray | None, size_m: float | None = None) -> TargetSpec:
    if not text and reference is None:
        raise ValueError("need a text description, a reference image, or both")
    clip = models.clip()
    inferred = None
    ref_crop = ref_hist = ref_emb = None
    if reference is not None:
        mask = object_mask(reference)
        ys, xs = np.nonzero(mask)
        pad = 4
        y0, y1 = max(0, ys.min() - pad), min(reference.shape[0], ys.max() + pad)
        x0, x1 = max(0, xs.min() - pad), min(reference.shape[1], xs.max() + pad)
        ref_crop = reference[y0:y1, x0:x1]
        ref_hist = hs_hist(reference, mask)
        ref_emb = clip.images([ref_crop] + _aerialize(ref_crop))
        inferred, conf = infer_label(ref_crop)
        log.info("vision.target.inferred_label", label=inferred, confidence=round(conf, 3))
    label = text or f"a {inferred}"
    noun = guess_object_noun(label) or (guess_object_noun(inferred) if inferred else None)
    size = size_m or (OBJECTS.get(noun, 1.0) if noun else 1.0)
    text_emb = clip.texts([t.format(label) for t in AERIAL_TEMPLATES]).mean(0, keepdims=True)
    text_emb /= np.linalg.norm(text_emb)
    others = [f"a {o}" for o in OBJECTS if o != noun and (noun is None or noun not in o and o not in noun)]
    neg_labels = BACKGROUND_PROMPTS + others
    neg_emb = clip.texts([AERIAL_TEMPLATES[0].format(n) for n in neg_labels])
    height = HEIGHTS.get(noun, 0.5) if noun else 0.5
    return TargetSpec(
        text,
        label,
        inferred,
        size,
        reference is not None,
        text_emb,
        neg_emb,
        ref_emb,
        ref_hist,
        ref_crop,
        neg_labels,
        height,
    )


@dataclass
class CropScore:
    score: float
    text: float | None
    image: float | None
    color: float | None
    size: float


def score_crops(
    target: TargetSpec,
    crops: list[np.ndarray],
    blob_masks: list[np.ndarray | None],
    blob_crops: list[np.ndarray],
    sizes_m: list[float],
    expected_sizes_m: list[float] | None = None,
) -> list[CropScore]:
    """Score crops (with context) for being the target. ``blob_crops`` are tight crops
    matching ``blob_masks`` for colour statistics."""
    if not crops:
        return []
    clip = models.clip()
    emb = clip.images(crops)
    out = []
    logits_pos = clip.logit_scale * emb @ target.text_emb.T  # (n,1)
    logits_neg = clip.logit_scale * emb @ target.neg_emb.T  # (n,N)
    for i in range(len(crops)):
        lg = np.concatenate([logits_pos[i], logits_neg[i]])
        p = np.exp(lg - lg.max())
        p_text = float(p[0] / p.sum())
        s_img = None
        if target.ref_emb is not None:
            sim = float((emb[i] @ target.ref_emb.T).max())
            s_img = float(np.clip((sim - 0.55) / 0.3, 0, 1))
        s_col = None
        if target.ref_hist is not None and blob_crops[i].size:
            s_col = hist_similarity(hs_hist(blob_crops[i], blob_masks[i]), target.ref_hist)
        expected = expected_sizes_m[i] if expected_sizes_m else target.size_m
        ratio = math.log(max(sizes_m[i], 1e-3) / expected)
        s_size = float(math.exp(-0.5 * (ratio / 0.7) ** 2))
        parts, weights = [p_text], [0.5]
        if s_img is not None:
            parts.append(s_img)
            weights.append(0.25)
        if s_col is not None:
            parts.append(s_col)
            weights.append(0.25)
        base = float(np.dot(parts, weights) / sum(weights))
        out.append(CropScore(base * (0.4 + 0.6 * s_size), p_text, s_img, s_col, s_size))
    return out
