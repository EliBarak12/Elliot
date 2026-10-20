"""Coverage path planning: lawnmower and spiral patterns sized from the camera footprint."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from backends.base import CameraModel
from common.geo import ne_between, offset
from vision.projection import altitude_for_pixels, footprint_m, ground_sample_distance_m


@dataclass
class EnergyModel:
    """Battery use per minute of flight; refined online from telemetry."""

    pct_per_min_cruise: float = 7.0
    climb_rate_ms: float = 2.5
    descent_rate_ms: float = 1.5
    turn_overhead_s: float = 4.0  # decelerate/turn/accelerate at each lane end
    samples: list[tuple[float, float]] = field(default_factory=list)  # (t, pct) while airborne

    def observe(self, t: float, pct: float | None, airborne: bool) -> None:
        if pct is None or not airborne:
            return
        self.samples.append((t, pct))
        self.samples = self.samples[-600:]
        if len(self.samples) > 20 and self.samples[-1][0] - self.samples[0][0] > 60:
            ts, ps = np.array(self.samples).T
            slope = -np.polyfit(ts, ps, 1)[0] * 60
            if 1.0 < slope < 40.0:  # ignore nonsense from integer-percent steps
                self.pct_per_min_cruise = float(0.7 * self.pct_per_min_cruise + 0.3 * slope)


@dataclass
class SearchPlan:
    id: str
    pattern: str
    altitude_m: float
    speed_ms: float
    overlap: float
    waypoints: list[tuple[float, float]]  # lat, lon
    area_polygon: list[tuple[float, float]]
    area_m2: float
    path_length_m: float
    est_time_s: float
    est_battery_pct: float
    lane_spacing_m: float
    footprint_m: tuple[float, float]
    gsd_cm: float
    target_px: float | None
    warnings: list[str]

    def summary(self) -> dict[str, object]:
        return {
            "plan_id": self.id,
            "pattern": self.pattern,
            "altitude_m": round(self.altitude_m, 1),
            "speed_ms": round(self.speed_ms, 1),
            "overlap": self.overlap,
            "n_waypoints": len(self.waypoints),
            "area_m2": round(self.area_m2),
            "path_length_m": round(self.path_length_m),
            "lane_spacing_m": round(self.lane_spacing_m, 1),
            "camera_footprint_m": [round(v, 1) for v in self.footprint_m],
            "ground_resolution_cm_per_px": round(self.gsd_cm, 2),
            "expected_target_size_px": None if self.target_px is None else round(self.target_px),
            "estimated_time_s": round(self.est_time_s),
            "estimated_battery_pct": round(self.est_battery_pct, 1),
            "warnings": self.warnings,
        }


def _to_local(poly: list[tuple[float, float]], ref: tuple[float, float]) -> Polygon:
    pts = [ne_between(ref[0], ref[1], la, lo) for la, lo in poly]
    return Polygon([(e, n) for n, e in pts])  # x=east, y=north


def circle_polygon(lat: float, lon: float, radius_m: float, n: int = 24) -> list[tuple[float, float]]:
    return [
        offset(lat, lon, radius_m * math.cos(a), radius_m * math.sin(a))
        for a in np.linspace(0, 2 * math.pi, n, endpoint=False)
    ]


def lawnmower(area: Polygon, spacing: float) -> list[tuple[float, float]]:
    """Boustrophedon lanes along the area's long axis, clipped to the polygon (x=E, y=N)."""
    rect = area.minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    edges = [(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(4)]
    long_edge = max(edges, key=lambda e: math.hypot(*e))
    ang = math.atan2(long_edge[1], long_edge[0])
    ca, sa = math.cos(-ang), math.sin(-ang)

    def rot(x: float, y: float, c: float, s: float) -> tuple[float, float]:
        return x * c - y * s, x * s + y * c

    local = Polygon([rot(x, y, ca, sa) for x, y in area.exterior.coords])
    minx, miny, maxx, maxy = local.bounds
    # inset the first/last lane by half a spacing so edge strips are imaged once, not twice
    n_lanes = max(1, math.ceil((maxy - miny) / spacing))
    offs = (maxy - miny - (n_lanes - 1) * spacing) / 2
    pts: list[tuple[float, float]] = []
    for i in range(n_lanes):
        y = miny + offs + i * spacing
        line: BaseGeometry = LineString([(minx - 1, y), (maxx + 1, y)]).intersection(local)
        if line.is_empty:
            continue
        coords = (
            list(line.coords)
            if line.geom_type == "LineString"
            else [c for g in getattr(line, "geoms", []) for c in g.coords]
        )
        if len(coords) < 2:
            continue
        a, b = (min(coords), max(coords))
        seg = [a, b] if i % 2 == 0 else [b, a]
        pts.extend(seg)
    c2, s2 = math.cos(ang), math.sin(ang)
    return [rot(x, y, c2, s2) for x, y in pts]


def spiral(area: Polygon, spacing: float) -> list[tuple[float, float]]:
    """Outward square spiral from the area centroid, clipped to the polygon."""
    c = area.centroid
    pts = [(c.x, c.y)]
    x, y, step, d = c.x, c.y, spacing, 0
    dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    minx, miny, maxx, maxy = area.bounds
    span = max(maxx - minx, maxy - miny)
    while step < span * 1.5:
        for _ in range(2):
            dx, dy = dirs[d % 4]
            x, y = x + dx * step, y + dy * step
            pts.append((x, y))
            d += 1
        step += spacing
    inside = [p for p in pts if area.buffer(spacing / 2).contains(Point(p))]
    return inside or [(c.x, c.y)]


def make_plan(
    polygon: list[tuple[float, float]],
    cam: CameraModel,
    target_size_m: float | None,
    altitude_m: float | None,
    overlap: float,
    pattern: str,
    speed_ms: float,
    start: tuple[float, float],
    home: tuple[float, float],
    energy: EnergyModel,
    min_target_px: float = 22.0,
    alt_limits: tuple[float, float] = (15.0, 40.0),
) -> SearchPlan:
    warnings: list[str] = []
    if altitude_m is None:
        if target_size_m:
            altitude_m = altitude_for_pixels(cam, target_size_m, min_target_px)
        else:
            altitude_m = 25.0
            warnings.append(
                "no search target set: defaulted to 25 m; call set_search_target first "
                "so altitude can be chosen from the target size"
            )
        altitude_m = float(np.clip(altitude_m, *alt_limits))
    ref = home
    area = _to_local(polygon, ref)
    if not area.is_valid or area.area < 1:
        raise ValueError("search area polygon is degenerate or self-intersecting")
    fw, fh = footprint_m(cam, altitude_m)
    spacing = fw * (1 - overlap)
    pts_local = lawnmower(area, spacing) if pattern == "lawnmower" else spiral(area, spacing)
    wps = [offset(ref[0], ref[1], y, x) for x, y in pts_local]
    s_ne = ne_between(ref[0], ref[1], *start)
    h_ne = (0.0, 0.0)
    path = LineString([(x, y) for x, y in pts_local]).length if len(pts_local) > 1 else 0.0
    transit = math.hypot(pts_local[0][0] - s_ne[1], pts_local[0][1] - s_ne[0])
    back = math.hypot(pts_local[-1][0] - h_ne[1], pts_local[-1][1] - h_ne[0])
    t = (path + transit + back) / speed_ms + len(wps) * energy.turn_overhead_s
    t += altitude_m / energy.climb_rate_ms + altitude_m / energy.descent_rate_ms + 15
    batt = t / 60 * energy.pct_per_min_cruise
    gsd = ground_sample_distance_m(cam, altitude_m)
    target_px = target_size_m / gsd if target_size_m else None
    if target_px is not None and target_px < 15:
        warnings.append(
            f"target will be only ~{target_px:.0f} px across at {altitude_m:.0f} m; "
            "detection is unreliable below ~20 px - fly lower"
        )
    if overlap < 0.1:
        warnings.append("overlap < 10%: gaps between lanes are likely when wind pushes the drone")
    return SearchPlan(
        id=f"p{uuid.uuid4().hex[:6]}",
        pattern=pattern,
        altitude_m=altitude_m,
        speed_ms=speed_ms,
        overlap=overlap,
        waypoints=wps,
        area_polygon=polygon,
        area_m2=area.area,
        path_length_m=path,
        est_time_s=t,
        est_battery_pct=batt,
        lane_spacing_m=spacing,
        footprint_m=(fw, fh),
        gsd_cm=gsd * 100,
        target_px=target_px,
        warnings=warnings,
    )
