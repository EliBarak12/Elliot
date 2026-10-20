"""Region proposals for aerial frames: "what stands out from the ground around it".

Open-vocabulary detectors (OWL-ViT/OWLv2) are too slow to run on every 1280x960 frame on
the CPU this runs on while Gazebo renders in software, and they struggle with objects of
~20 px. Aerial search over terrain has a cheaper prior: objects differ in colour from
their local background. We flag pixels far (in CIELAB) from a heavily blurred background
estimate, group them into blobs, and keep blobs whose ground size fits the target. A
learned scorer (vision/matcher.py) then decides what each blob is.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Proposal:
    x0: int
    y0: int
    x1: int
    y1: int  # bbox in full-resolution pixels
    area_px: int
    contrast: float  # mean Lab distance from background inside the blob
    mask: np.ndarray | None = None  # blob mask within the bbox (full res), for colour stats

    @property
    def center(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2

    @property
    def size_px(self) -> float:
        return float(max(self.x1 - self.x0, self.y1 - self.y0))


@dataclass
class ProposalConfig:
    downscale: int = 2
    bg_blur_m: float = 6.0  # background scale on the ground
    min_contrast: float = 18.0  # Lab units
    k_sigma: float = 3.0
    min_size_m: float = 0.15
    max_size_m: float = 8.0
    max_proposals: int = 40
    suppress_shadows: bool = True
    shadow_max_brightness: float = 0.8  # pixel/background brightness below this ...
    shadow_max_chroma: float = 0.06  # ... with chromaticity this close = shadow
    border_px: int = 4


def propose(image: np.ndarray, gsd_m: float, cfg: ProposalConfig | None = None) -> list[Proposal]:
    """Blobs that differ from their surroundings and have a plausible ground size."""
    cfg = cfg or ProposalConfig()
    ds = cfg.downscale
    small = cv2.resize(image, (image.shape[1] // ds, image.shape[0] // ds), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
    gsd_small = gsd_m * ds
    k = int(max(15, round(cfg.bg_blur_m / gsd_small))) | 1
    # median is robust to the objects themselves; run it on a further-downsampled copy
    f = 4
    tiny = cv2.resize(lab, (lab.shape[1] // f, lab.shape[0] // f), interpolation=cv2.INTER_AREA)
    kt = max(3, (k // f) | 1)
    bg_tiny = np.stack(
        [cv2.medianBlur(np.ascontiguousarray(tiny[..., c]).astype(np.uint8), min(kt, 255)) for c in range(3)], axis=-1
    ).astype(np.float32)
    bg = cv2.resize(bg_tiny, (lab.shape[1], lab.shape[0]), interpolation=cv2.INTER_LINEAR)
    # weight chroma more than lightness: shadows and grass texture are mostly L changes
    d = lab - bg
    dist = np.sqrt(0.5 * d[..., 0] ** 2 + 1.5 * d[..., 1] ** 2 + 1.5 * d[..., 2] ** 2)
    thr = max(
        cfg.min_contrast, float(np.median(dist) + cfg.k_sigma * 1.4826 * np.median(np.abs(dist - np.median(dist))))
    )
    mask = (dist > thr).astype(np.uint8)
    if cfg.suppress_shadows:
        # Cast shadows: darker than the local background but the same hue/chroma. With a low
        # sun they glue onto the object and push the blob past the size window (a person and
        # their shadow measured ~2 m in run medium-2001). Drop those pixels from the mask.
        # Lab chroma is not brightness-invariant, so compare normalised RGB chromaticity.
        bg_rgb = cv2.cvtColor(np.clip(bg, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32) + 1
        px = small.astype(np.float32) + 1
        s_px, s_bg = px.sum(axis=2), bg_rgb.sum(axis=2)
        chroma_shift = np.abs(px / s_px[..., None] - bg_rgb / s_bg[..., None]).sum(axis=2)
        ratio = s_px / s_bg
        shadow = (ratio < cfg.shadow_max_brightness) & (ratio > 0.15) & (chroma_shift < cfg.shadow_max_chroma)
        mask[shadow] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out: list[Proposal] = []
    h, w = mask.shape
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        size_m = max(bw, bh) * gsd_small
        if size_m < cfg.min_size_m or size_m > cfg.max_size_m:
            continue
        if area < 4:
            continue
        # thin lines (lane markings, road edges, fences) are not objects
        if min(bw, bh) * gsd_small < 0.08 or area / float(bw * bh) < 0.15:
            continue
        if x <= cfg.border_px or y <= cfg.border_px or x + bw >= w - cfg.border_px or y + bh >= h - cfg.border_px:
            continue  # cut by the frame edge; a later frame sees it whole
        blob = labels[y : y + bh, x : x + bw] == i
        contrast = float(dist[y : y + bh, x : x + bw][blob].mean())
        full_mask = cv2.resize(blob.astype(np.uint8), (bw * ds, bh * ds), interpolation=cv2.INTER_NEAREST)
        out.append(Proposal(x * ds, y * ds, (x + bw) * ds, (y + bh) * ds, int(area) * ds * ds, contrast, full_mask))
    out.sort(key=lambda p: p.contrast * np.sqrt(p.area_px), reverse=True)
    return out[: cfg.max_proposals]


def crop_square(
    image: np.ndarray, p: Proposal, context: float = 1.8, min_px: int = 24
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Square crop around a proposal with some context, clipped to the image."""
    cx, cy = p.center
    half = max(p.size_px * context, min_px) / 2
    x0, y0 = int(max(0, cx - half)), int(max(0, cy - half))
    x1, y1 = int(min(image.shape[1], cx + half)), int(min(image.shape[0], cy + half))
    return image[y0:y1, x0:x1], (x0, y0, x1, y1)
