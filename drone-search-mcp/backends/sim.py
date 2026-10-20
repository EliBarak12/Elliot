"""SimBackend: ArduCopter SITL over MAVLink + Gazebo camera frames from shared memory."""

from __future__ import annotations

import os

from backends.ardupilot import ArduPilotBackend
from backends.camera import ShmFrameSource


class SimBackend(ArduPilotBackend):
    name = "sitl"

    def __init__(self, connection: str | None = None, frame_dir: str | None = None) -> None:
        super().__init__(
            connection or os.environ.get("DSM_MAVLINK", "tcp:127.0.0.1:5760"),
            ShmFrameSource(frame_dir or os.environ.get("DSM_FRAME_DIR", "/dev/shm/drone_search")),
            # SITL in lockstep with Gazebo runs on the physics clock, so frame stamps and
            # MAVLink time_boot_ms share a timebase.
            frame_clock_offset_s=float(os.environ.get("DSM_FRAME_CLOCK_OFFSET", "0")),
        )
