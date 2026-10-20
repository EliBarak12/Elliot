"""SimBackend: ArduCopter SITL over MAVLink + Gazebo camera frames from shared memory."""

from __future__ import annotations

import json
import os
from pathlib import Path

from backends.ardupilot import ArduPilotBackend
from backends.camera import ShmFrameSource, load_calibration

DEFAULT_CALIBRATION = Path(__file__).resolve().parents[1] / "sim" / "camera_calibration.json"


class SimBackend(ArduPilotBackend):
    name = "sitl"
    max_zoom = 6.0

    def __init__(
        self, connection: str | None = None, frame_dir: str | None = None, calibration: str | None = None
    ) -> None:
        # The calibration plays the role of a real camera's checkerboard + timing calibration.
        # It is measured (eval/projection_check.py), not copied from the simulator.
        cal = load_calibration(calibration or os.environ.get("DSM_CAMERA_CALIBRATION", str(DEFAULT_CALIBRATION)))
        offset = os.environ.get("DSM_FRAME_CLOCK_OFFSET")
        super().__init__(
            connection or os.environ.get("DSM_MAVLINK", "tcp:127.0.0.1:5760"),
            ShmFrameSource(frame_dir or os.environ.get("DSM_FRAME_DIR", "/dev/shm/drone_search"), calibration=cal),
            # Frame stamps are arrival times on the sim (= SITL boot) clock; the measured
            # pipeline latency maps them back to exposure time.
            frame_clock_offset_s=float(offset)
            if offset is not None
            else float((cal or {}).get("frame_clock_offset_s", 0.0)),
        )

    def set_zoom(self, zoom: float) -> float:
        """Zoom the simulated camera through the frame bridge's control file (a real camera
        would take MAV_CMD_SET_CAMERA_ZOOM or its own SDK call)."""
        z = float(min(max(zoom, 1.0), self.max_zoom))
        frame_dir = Path(os.environ.get("DSM_FRAME_DIR", "/dev/shm/drone_search"))
        tmp = frame_dir / ".control.json.tmp"
        tmp.write_text(json.dumps({"zoom": z}))
        os.replace(tmp, frame_dir / "control.json")
        return z
