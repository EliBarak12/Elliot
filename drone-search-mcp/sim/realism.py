"""Real-world camera degradation, applied on the simulator side of the frame bridge.

The server must never get frames that are cleaner than a real drone's video link would
deliver, or everything we tune on SITL is tuned for a camera that does not exist. Applied
in order to each Gazebo frame:

1. lens distortion   - radial (k1, k2); the server undistorts with a *measured* calibration
2. motion blur       - along the drone's velocity, length = speed * exposure / GSD
3. exposure          - slow auto-exposure gain drift + vignetting
4. sensor noise      - Gaussian read noise
5. compression       - JPEG at video-link quality (blocking, colour bleeding)

Timing is degraded by the grabber itself: frames are delivered late (pipeline latency +
jitter), some are dropped, and the timestamp is the *arrival* time - as on a companion
computer that stamps frames when they come off the decoder.

Pure numpy + PIL so it runs in the system Python that hosts the gz-transport bindings.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

try:  # OpenCV makes this ~10x faster; it must keep up with the camera rate or frames back up
    import cv2 as _cv2
except ImportError:  # pragma: no cover - pure numpy fallback
    _cv2 = None

# The physical lens of the simulated camera (fixed: a property of the hardware).
TRUE_K1 = -0.06
TRUE_K2 = 0.008


@dataclass
class RealismProfile:
    enabled: bool = True
    jpeg_quality: int = 70
    noise_sigma: float = 3.0
    exposure_s: float = 0.006
    vignette: float = 0.25
    gain_walk: float = 0.01  # per-frame std of log-gain random walk
    latency_s: float = 0.20
    latency_jitter_s: float = 0.03
    drop_prob: float = 0.05
    k1: float = TRUE_K1
    k2: float = TRUE_K2

    @classmethod
    def from_dict(cls, d: dict | None) -> RealismProfile:
        if not d:
            return cls(enabled=False)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class Degrader:
    def __init__(self, profile: RealismProfile, width: int, height: int, fx: float, seed: int = 0) -> None:
        self.p = profile
        self.rng = np.random.default_rng(seed)
        self.log_gain = 0.0
        self.fx = fx
        h, w = height, width
        cx, cy = w / 2, h / 2
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        # Distorted output pixel (u,v) shows the scene point whose undistorted normalised
        # coordinate r_u satisfies r_d = r_u * (1 + k1 r_u^2 + k2 r_u^4). Invert by fixed-point.
        xd, yd = (xs - cx) / fx, (ys - cy) / fx
        xu, yu = xd.copy(), yd.copy()
        for _ in range(6):
            r2 = xu * xu + yu * yu
            f = 1 + profile.k1 * r2 + profile.k2 * r2 * r2
            xu, yu = xd / f, yd / f
        self.map_x = np.clip(xu * fx + cx, 0, w - 1.001)
        self.map_y = np.clip(yu * fx + cy, 0, h - 1.001)
        r = np.sqrt(((xs - cx) / cx) ** 2 + ((ys - cy) / cy) ** 2) / math.sqrt(2)
        self.vignette = (1 - profile.vignette * r**2)[..., None].astype(np.float32)
        self._noise_bank: np.ndarray | None = None
        self._noise_buf: np.ndarray | None = None
        self.vignette3 = np.repeat(self.vignette, 3, axis=2)

    def _remap(self, img: np.ndarray) -> np.ndarray:
        if _cv2 is not None:
            return _cv2.remap(img, self.map_x, self.map_y, _cv2.INTER_LINEAR).astype(np.float32)
        x0 = self.map_x.astype(np.int32)
        y0 = self.map_y.astype(np.int32)
        fx = (self.map_x - x0)[..., None]
        fy = (self.map_y - y0)[..., None]
        a = img[y0, x0].astype(np.float32)
        b = img[y0, x0 + 1].astype(np.float32)
        c = img[y0 + 1, x0].astype(np.float32)
        d = img[y0 + 1, x0 + 1].astype(np.float32)
        return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy

    @staticmethod
    def _motion_blur(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
        n = int(round(math.hypot(dx, dy)))
        if n < 1:
            return img
        if _cv2 is not None:
            k = np.zeros((2 * n + 1, 2 * n + 1), np.float32)
            _cv2.line(k, (int(n - dx / 2), int(n - dy / 2)), (int(n + dx / 2), int(n + dy / 2)), 1.0, 1)
            return _cv2.filter2D(img, -1, k / max(k.sum(), 1e-6))
        acc = np.zeros_like(img)
        for i in range(n + 1):
            sx = int(round(dx * (i / n - 0.5)))
            sy = int(round(dy * (i / n - 0.5)))
            acc += np.roll(np.roll(img, sy, axis=0), sx, axis=1)
        return acc / (n + 1)

    def apply(self, rgb: np.ndarray, image_vel_px_s: tuple[float, float], alt_m: float) -> bytes:
        """Return a degraded frame as JPEG bytes. ``image_vel_px_s`` is ground motion in the
        image (pixels/s) from the drone's velocity."""
        p = self.p
        img = self._remap(rgb)
        vx, vy = image_vel_px_s
        img = self._motion_blur(img, vx * p.exposure_s, vy * p.exposure_s)
        self.log_gain = float(np.clip(self.log_gain + self.rng.normal(0, p.gain_walk), -0.25, 0.25))
        if _cv2 is not None:
            img = _cv2.multiply(img, self.vignette3, scale=math.exp(self.log_gain))
            if self._noise_buf is None:
                self._noise_buf = np.empty(img.shape, np.float32)
            _cv2.randn(self._noise_buf, 0.0, p.noise_sigma)
            u8 = _cv2.add(img, self._noise_buf).clip(0, 255).astype(np.uint8)
        else:
            img = img * math.exp(self.log_gain) * self.vignette
            img = img + self._noise(img.shape, p.noise_sigma)
            u8 = np.clip(img, 0, 255).astype(np.uint8)
        if _cv2 is not None:
            ok, enc = _cv2.imencode(
                ".jpg", _cv2.cvtColor(u8, _cv2.COLOR_RGB2BGR), [_cv2.IMWRITE_JPEG_QUALITY, int(p.jpeg_quality)]
            )
            if ok:
                return enc.tobytes()
        buf = io.BytesIO()
        Image.fromarray(u8).save(buf, format="JPEG", quality=int(p.jpeg_quality))
        return buf.getvalue()

    def _noise(self, shape: tuple[int, ...], sigma: float) -> np.ndarray:
        # drawing fresh Gaussian noise for 3.7 M values per frame is the slowest step;
        # reuse a pre-drawn bank with a random offset (statistically indistinguishable here)
        if self._noise_bank is None or self._noise_bank.size < 2 * int(np.prod(shape)):
            self._noise_bank = self.rng.normal(0, 1, 2 * int(np.prod(shape))).astype(np.float32)
        n = int(np.prod(shape))
        o = int(self.rng.integers(0, self._noise_bank.size - n))
        return sigma * self._noise_bank[o : o + n].reshape(shape)
