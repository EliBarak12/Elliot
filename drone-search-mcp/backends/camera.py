"""Camera frame sources. A source yields raw images plus the camera clock timestamp."""

from __future__ import annotations

import abc
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
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


def zoomed(cam: CameraModel, zoom: float) -> CameraModel:
    """Intrinsics at an optical zoom factor (focal length multiplied by ``zoom``).

    The simulated lens distortion is a fixed pixel-space warp, so its coefficients scale
    with the focal length; on a real zoom lens use the calibration for that zoom step.
    """
    s = zoom
    return CameraModel(cam.width, cam.height, cam.fx * s, cam.fy * s, cam.cx, cam.cy, cam.k1 * s * s, cam.k2 * s**4)


class FrameSource(abc.ABC):
    @abc.abstractmethod
    def read(self) -> RawFrame | None:
        """Latest frame, or None if there is none yet."""


def load_calibration(path: str | os.PathLike[str] | None) -> dict | None:
    """Measured camera calibration (intrinsics, distortion, frame timing offset), or None."""
    if not path or not Path(path).is_file():
        return None
    cal = json.loads(Path(path).read_text())
    log.info(
        "camera.calibration.loaded",
        path=str(path),
        fx=cal.get("fx"),
        k1=cal.get("k1"),
        frame_clock_offset_s=cal.get("frame_clock_offset_s"),
    )
    return cal


class ShmFrameSource(FrameSource):
    """Reads the frames that ``sim/frame_grabber.py`` writes to a shared-memory dir.

    Intrinsics come from the measured calibration when one is given (always, for a real
    camera); the simulator's ideal intrinsics are only used as a fallback in ideal mode.
    """

    def __init__(
        self, directory: str | os.PathLike[str], hfov_rad: float | None = None, calibration: dict | None = None
    ) -> None:
        self.dir = Path(directory)
        self.hfov_rad = hfov_rad
        self.calibration = calibration
        self._cache: RawFrame | None = None

    def read(self) -> RawFrame | None:
        try:
            meta = json.loads((self.dir / "frame.json").read_text())
        except (OSError, ValueError):
            return self._cache
        if self._cache is not None and self._cache.seq == meta["seq"]:
            return self._cache
        w, h = int(meta["width"]), int(meta["height"])
        if meta.get("encoding") == "jpeg":
            try:
                buf = np.fromfile(self.dir / "frame.jpg", dtype=np.uint8)
                img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            except (OSError, cv2.error):
                return self._cache
            if img is None or img.shape[:2] != (h, w):
                return self._cache
            data = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        else:
            try:
                data = np.fromfile(self.dir / "frame.rgb", dtype=np.uint8)
            except OSError:
                return self._cache
            if data.size != w * h * 3:  # caught mid-replace; keep the previous frame
                return self._cache
        c = self.calibration
        if c is not None:
            cam = CameraModel(w, h, c["fx"], c["fy"], c["cx"], c["cy"], c.get("k1", 0.0), c.get("k2", 0.0))
        elif "fx" in meta:
            cam = CameraModel(w, h, meta["fx"], meta["fy"], meta["cx"], meta["cy"])
        else:
            hfov = self.hfov_rad or 1.2
            f = w / 2 / math.tan(hfov / 2)
            cam = CameraModel(w, h, f, f, w / 2, h / 2)
        zoom = float(meta.get("zoom", 1.0))
        if zoom != 1.0 and (c is not None or "fx" not in meta):
            cam = zoomed(cam, zoom)
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
