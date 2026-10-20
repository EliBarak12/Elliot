"""RealBackend placeholder: real ArduCopter hardware (and later a Tello backend).

Deliberately not implemented. The ArduPilot MAVLink code in ``backends/ardupilot.py`` is
shared with SITL; what a real vehicle still needs is a camera source (RTSP/UDP stream with
a timestamp that can be related to the autopilot clock), a measured camera calibration,
and a field-test checklist - see REPORT.md. The server refuses to fly anything whose
``is_simulation()`` is False regardless, so wiring this in requires a code change and a
deliberate flag, not a config typo.
"""

from __future__ import annotations

from backends.ardupilot import ArduPilotBackend


class RealBackend(ArduPilotBackend):
    name = "real"

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "RealBackend is not available yet: simulation only. See REPORT.md for what is "
            "needed before a real-drone test."
        )
