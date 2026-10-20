"""Camera frame sources. A source yields raw images plus the camera clock timestamp."""

from __future__ import annotations

import abc
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import structlog

from backends.base import CameraModel

log = structlog.get_logger(__name__)


@dataclass
class RawFrame:
    image: np.ndarray
    camera: CameraModel
    seq: int
    stamp_s: float  # camera clock; for Gazebo this is sim time == SITL boot time
    wall_time: float


class FrameSource(abc.ABC):
    @abc.abstractmethod
    def read(self) -> RawFrame | None:
        """Latest frame, or None if there is none yet."""


class ShmFrameSource(FrameSource):
    """Reads the frames that ``sim/frame_grabber.py`` writes to a shared-memory dir."""

    def __init__(self, directory: str | os.PathLike[str], hfov_rad: float | None = None) -> None:
        self.dir = Path(directory)
        self.hfov_rad = hfov_rad
        self._cache: RawFrame | None = None

    def read(self) -> RawFrame | None:
        try:
            meta = json.loads((self.dir / "frame.json").read_text())
        except (OSError, ValueError):
            return self._cache
        if self._cache is not None and self._cache.seq == meta["seq"]:
            return self._cache
        w, h = int(meta["width"]), int(meta["height"])
        try:
            data = np.fromfile(self.dir / "frame.rgb", dtype=np.uint8)
        except OSError:
            return self._cache
        if data.size != w * h * 3:  # caught mid-replace; keep the previous frame
            return self._cache
        if "fx" in meta:
            cam = CameraModel(w, h, meta["fx"], meta["fy"], meta["cx"], meta["cy"])
        else:
            hfov = self.hfov_rad or 1.2
            f = w / 2 / math.tan(hfov / 2)
            cam = CameraModel(w, h, f, f, w / 2, h / 2)
        self._cache = RawFrame(
            data.reshape(h, w, 3),
            cam,
            int(meta["seq"]),
            float(meta["stamp_sim_s"]),
            float(meta["wall_time"]),
        )
        return self._cache

    def wait(self, timeout_s: float) -> RawFrame | None:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            f = self.read()
            if f is not None:
                return f
            time.sleep(0.2)
        return None
