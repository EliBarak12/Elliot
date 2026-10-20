"""Flight recorder: camera frames + telemetry + detections, for videos and post-mortems.

Recording is cheap on purpose (a 640x480 JPEG and one JSON line per frame, at a few Hz);
``scripts/make_video.py`` renders the annotated MP4 afterwards, off the flight path.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import structlog

from backends.base import DroneBackend, Frame

log = structlog.get_logger(__name__)


class FlightRecorder:
    def __init__(
        self,
        backend: DroneBackend,
        out_dir: Path,
        rate_hz: float = 4.0,
        context: Callable[[], dict[str, Any]] | None = None,
        enabled: bool = True,
    ) -> None:
        self.backend = backend
        self.out_dir = out_dir
        self.rate_hz = rate_hz
        self.context = context
        self.enabled = enabled
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._dets: dict[int, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self.segment: Path | None = None
        self._count = 0

    def note_detections(self, f: Frame, dets: list[Any]) -> None:
        if not self.enabled:
            return
        sx = 640 / f.camera.width
        sy = 480 / f.camera.height
        with self._lock:
            self._dets[f.seq] = [
                {"bbox": [d.bbox[0] * sx, d.bbox[1] * sy, d.bbox[2] * sx, d.bbox[3] * sy], "score": round(d.score, 3)}
                for d in dets
            ]
            if len(self._dets) > 200:
                for k in sorted(self._dets)[:100]:
                    del self._dets[k]

    def start(self, name: str) -> None:
        if not self.enabled:
            return
        self.stop()
        self.segment = self.out_dir / "recording" / f"{time.strftime('%H%M%S')}_{name}"
        (self.segment / "frames").mkdir(parents=True, exist_ok=True)
        self._count = 0
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="recorder")
        self._thread.start()
        log.info("recorder.start", segment=str(self.segment))

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=3)
        self._thread = None
        if self.segment is not None and self.context is not None:
            try:
                (self.segment / "context.json").write_text(json.dumps(self.context(), default=str))
            except Exception:
                log.error("recorder.context_failed", exc_info=True)
        log.info("recorder.stop", segment=str(self.segment), frames=self._count)

    def _run(self) -> None:
        assert self.segment is not None
        last_seq = -1
        log_f = open(self.segment / "telemetry.jsonl", "a")  # noqa: SIM115
        try:
            while not self._stop.wait(1.0 / self.rate_hz):
                try:
                    f = self.backend.latest_frame(max_age_s=2.0)
                    t = self.backend.telemetry()
                    if f is None or f.seq == last_seq:
                        continue
                    last_seq = f.seq
                    small = cv2.resize(f.image, (640, 480), interpolation=cv2.INTER_AREA)
                    name = f"{self._count:05d}.jpg"
                    cv2.imwrite(
                        str(self.segment / "frames" / name),
                        cv2.cvtColor(small, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 85],
                    )
                    self._count += 1
                    with self._lock:
                        dets = [d for s, ds in self._dets.items() if f.seq - 3 <= s <= f.seq for d in ds]
                    rec = {
                        "frame": name,
                        "wall": time.time(),
                        "seq": f.seq,
                        "lat": t.lat,
                        "lon": t.lon,
                        "alt": t.alt_rel_m,
                        "yaw": t.yaw_rad,
                        "battery": t.battery_pct,
                        "mode": t.mode,
                        "speed": round(t.groundspeed_ms, 2),
                        "dets": dets,
                    }
                    log_f.write(json.dumps(rec) + "\n")
                    log_f.flush()
                except Exception:
                    log.error("recorder.frame_failed", exc_info=True)
        finally:
            log_f.close()
