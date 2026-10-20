"""Flat-earth geodesy matching ArduPilot's own (Location::offset / get_distance_NE).

Search areas are a few hundred metres across, so an equirectangular approximation with
ArduPilot's constants keeps our maths bit-compatible with the autopilot's: a point we
compute as "20 m north" is the point the vehicle flies to when told the same.
"""

from __future__ import annotations

import math

# ArduPilot LATLON_TO_M: metres per 1e-7 degree of latitude
M_PER_DEG = 0.011131884502145034 * 1e7


def lon_scale(lat: float) -> float:
    return max(math.cos(math.radians(lat)), 0.01)


def offset(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    return lat + north_m / M_PER_DEG, lon + east_m / (M_PER_DEG * lon_scale(lat))


def ne_between(lat0: float, lon0: float, lat1: float, lon1: float) -> tuple[float, float]:
    """(north, east) metres from point 0 to point 1."""
    return (lat1 - lat0) * M_PER_DEG, (lon1 - lon0) * M_PER_DEG * lon_scale(lat0)


def distance_m(lat0: float, lon0: float, lat1: float, lon1: float) -> float:
    n, e = ne_between(lat0, lon0, lat1, lon1)
    return math.hypot(n, e)


def bearing_deg(lat0: float, lon0: float, lat1: float, lon1: float) -> float:
    n, e = ne_between(lat0, lon0, lat1, lon1)
    return math.degrees(math.atan2(e, n)) % 360
