"""Structured, actionable errors. Agents see {code, message, next_step}; stack traces go to logs."""

from __future__ import annotations

from typing import Any


class DroneSearchError(Exception):
    code = "INTERNAL"
    next_step = "Call get_status to see the vehicle state, then retry or return_home."

    def __init__(self, message: str, next_step: str | None = None, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        if next_step:
            self.next_step = next_step
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message, "next_step": self.next_step}
        if self.details:
            err["details"] = self.details
        return {"error": err}


class ActuationDisabled(DroneSearchError):
    code = "ACTUATION_DISABLED"
    next_step = (
        "This server was started read-only. Restart it with --allow-actuation (simulation only) "
        "to fly; read-only tools (get_status, capture_image, plan_search) still work."
    )


class NotSimulation(DroneSearchError):
    code = "NOT_SIMULATION"
    next_step = "Flight is only allowed against ArduPilot SITL. Check that sim_up.sh is running."


class SafetyViolation(DroneSearchError):
    code = "SAFETY_VIOLATION"


class InvalidArgument(DroneSearchError):
    code = "INVALID_ARGUMENT"
    next_step = "Fix the argument as described and call the tool again."


class NotFound(DroneSearchError):
    code = "NOT_FOUND"


class StateConflict(DroneSearchError):
    code = "STATE_CONFLICT"


class VehicleError(DroneSearchError):
    code = "VEHICLE_ERROR"
    next_step = "Call get_status. If the vehicle is airborne and unresponsive, call emergency_stop."


class Aborted(DroneSearchError):
    code = "ABORTED"
    next_step = "Call get_status to see why and where the vehicle is."
