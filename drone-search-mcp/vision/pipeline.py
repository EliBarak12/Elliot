"""Per-frame detection and multi-frame candidate tracking.

FrameAnalyzer:   frame -> proposals -> scored crops -> ground-projected detections
CandidateTracker: detections from many frames -> deduplicated candidates on the ground
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

import cv2
import numpy as np
import structlog

from backends.base import Frame
from common.geo import distance_m, ne_between
from vision.matcher import CropScore, TargetSpec, score_crops
from vision.projection import ground_sample_distance_m, pixel_to_ground
from vision.proposals import ProposalConfig, crop_square, propose

log = structlog.get_logger(__name__)


@dataclass
class Detection:
    lat: float
    lon: float
    score: float
    cues: CropScore
    bbox: tuple[int, int, int, int]
    size_m: float
    frame_seq: int
    alt_m: float
    crop: np.ndarray  # context crop, RGB


@dataclass
class AnalyzerConfig:
    min_score: float = 0.30  # detections below this are dropped before tracking
    # Frames taken while the body rotates faster than this are skipped: the gimbal and the
    # pose stream lag the motion and projection error jumps from ~0.2 m to several metres
    # (calibration flight, EXPERIMENTS.md v0).
    max_rotation_dps: float = 3.0
    proposals: ProposalConfig = field(default_factory=ProposalConfig)
    crop_context: float = 2.0


class FrameAnalyzer:
    def __init__(self, target: TargetSpec, cfg: AnalyzerConfig | None = None) -> None:
        self.target = target
        self.cfg = cfg or AnalyzerConfig()
        self.skipped_unsteady = 0

    def analyze(self, frame: Frame) -> list[Detection]:
        pose = frame.pose
        if pose.alt_rel_m is None or pose.alt_rel_m < 2:
            return []
        if pose.tilt_rate_dps > self.cfg.max_rotation_dps:
            self.skipped_unsteady += 1
            return []
        gsd = ground_sample_distance_m(frame.camera, pose.alt_rel_m)
        pc = self.cfg.proposals
        # size window around the target: generous, the scorer's size prior does the rest
        pc = ProposalConfig(
            **{
                **pc.__dict__,
                "min_size_m": max(0.12, self.target.size_m * 0.25),
                "max_size_m": max(1.5, self.target.size_m * 2.5),
            }
        )
        props = propose(frame.image, gsd, pc)
        if not props:
            return []
        crops, tight, masks, sizes, boxes = [], [], [], [], []
        for p in props:
            c, box = crop_square(frame.image, p, self.cfg.crop_context, min_px=32)
            crops.append(c)
            boxes.append(box)
            tight.append(frame.image[p.y0 : p.y1, p.x0 : p.x1])
            m = p.mask
            if m is not None and m.shape[:2] != (p.y1 - p.y0, p.x1 - p.x0):
                m = cv2.resize(m, (p.x1 - p.x0, p.y1 - p.y0), interpolation=cv2.INTER_NEAREST)
            masks.append(m)
            sizes.append(p.size_px * gsd)
        scores = score_crops(self.target, crops, masks, tight, sizes)
        dets = []
        for p, s, box, c, size in zip(props, scores, boxes, crops, sizes, strict=True):
            if s.score < self.cfg.min_score:
                continue
            u, v = p.center
            g = pixel_to_ground(u, v, frame.camera, pose, pose.gimbal_pitch_deg)
            if g is None:
                continue
            dets.append(Detection(g.lat, g.lon, s.score, s, box, size, frame.seq, pose.alt_rel_m, c))
        return dets


@dataclass
class Candidate:
    id: str
    lat: float
    lon: float
    best_score: float
    n_obs: int
    n_frames_covered: int  # frames whose footprint contained this spot (hit or miss)
    best_crop: np.ndarray
    best_cues: CropScore
    size_m: float
    first_seen_seq: int
    observations: list[tuple[float, float, float]] = field(default_factory=list)  # lat, lon, score
    inspected: bool = False
    closeup_path: str | None = None
    closeup_score: float | None = None
    status: str = "unverified"  # unverified | inspected | reported | rejected

    @property
    def confidence(self) -> float:
        """Best score, discounted when one lucky frame is the only evidence."""
        top = sorted((o[2] for o in self.observations), reverse=True)[:3]
        mean_top = float(np.mean(top))
        support = 1 - 0.5 ** len(self.observations)
        hit_rate = len(self.observations) / max(1, self.n_frames_covered)
        return float(mean_top * (0.6 + 0.4 * support) * (0.7 + 0.3 * min(1.0, hit_rate * 1.5)))

    @property
    def position_spread_m(self) -> float:
        if len(self.observations) < 2:
            return float("nan")
        ne = [ne_between(self.lat, self.lon, la, lo) for la, lo, _ in self.observations]
        return float(np.sqrt(np.mean([n * n + e * e for n, e in ne])))


class CandidateTracker:
    def __init__(self, merge_radius_m: float = 3.0) -> None:
        self.merge_radius_m = merge_radius_m
        self.candidates: dict[str, Candidate] = {}
        self._next = 1
        self._lock = threading.Lock()

    def add(self, dets: list[Detection]) -> list[Candidate]:
        touched = []
        with self._lock:
            for d in dets:
                radius = max(self.merge_radius_m, 0.75 * d.size_m)
                best, best_d = None, float("inf")
                for c in self.candidates.values():
                    dist = distance_m(c.lat, c.lon, d.lat, d.lon)
                    if dist < radius and dist < best_d:
                        best, best_d = c, dist
                if best is None:
                    cid = f"c{self._next}"
                    self._next += 1
                    best = Candidate(cid, d.lat, d.lon, d.score, 0, 0, d.crop, d.cues, d.size_m, d.frame_seq)
                    self.candidates[cid] = best
                best.observations.append((d.lat, d.lon, d.score))
                best.n_obs += 1
                w = np.array([o[2] for o in best.observations])
                best.lat = float(np.dot(w, [o[0] for o in best.observations]) / w.sum())
                best.lon = float(np.dot(w, [o[1] for o in best.observations]) / w.sum())
                if d.score > best.best_score or best.n_obs == 1:
                    best.best_score, best.best_crop, best.best_cues = d.score, d.crop, d.cues
                    best.size_m = d.size_m
                touched.append(best)
        return touched

    def note_coverage(self, frame: Frame) -> None:
        """Count frames that saw each candidate's spot, so one-frame flukes rank lower."""
        pose = frame.pose
        if pose.lat is None or pose.lon is None or pose.alt_rel_m is None or pose.alt_rel_m < 2:
            return
        half_w = frame.camera.width / 2 * pose.alt_rel_m / frame.camera.fx * 0.9
        half_h = frame.camera.height / 2 * pose.alt_rel_m / frame.camera.fy * 0.9
        with self._lock:
            for c in self.candidates.values():
                n, e = ne_between(pose.lat, pose.lon, c.lat, c.lon)
                fwd = n * math.cos(pose.yaw_rad) + e * math.sin(pose.yaw_rad)
                right = -n * math.sin(pose.yaw_rad) + e * math.cos(pose.yaw_rad)
                if abs(right) < half_w and abs(fwd) < half_h:
                    c.n_frames_covered += 1

    def ranked(self, min_confidence: float = 0.0) -> list[Candidate]:
        with self._lock:
            cs = [c for c in self.candidates.values() if c.confidence >= min_confidence and c.status != "rejected"]
        return sorted(cs, key=lambda c: c.confidence, reverse=True)

    def get(self, cid: str) -> Candidate | None:
        return self.candidates.get(cid)
