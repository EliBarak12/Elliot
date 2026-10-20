"""Generate the Gazebo world SDF for a scenario.

The base field (ground, roads, buildings, trees, launch pad) is deterministic from
``sim/field.json``; a scenario adds its target and distractor objects on top. World
coordinates are Gazebo ENU: +x east, +y north, metres from the launch point, which is
also the SITL home location (``field.json`` -> ``origin``).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
GEN = HERE / "generated"
FUEL = "https://fuel.gazebosim.org/1.0/OpenRobotics/models/"


def load_field() -> dict[str, Any]:
    return json.loads((HERE / "field.json").read_text())


def tree_positions(field: dict[str, Any]) -> list[tuple[str, float, float, float]]:
    """Deterministic tree layout: (model, x, y, yaw), kept off roads, houses and launch."""
    rng = np.random.default_rng(field["seed"] + 1)
    cfg = field["trees"]
    out: list[tuple[str, float, float, float]] = []
    tries = 0
    while len(out) < cfg["count"] and tries < 5000:
        tries += 1
        x, y = rng.uniform(-110, 110, 2)
        if blocked(field, x, y, cfg["keepout_m"], trees=out):
            continue
        model = cfg["models"][int(rng.integers(0, len(cfg["models"])))]
        out.append((model, float(x), float(y), float(rng.uniform(0, 2 * math.pi))))
    return out


def _dist_to_segment(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    ab = b - a
    t = float(np.clip(np.dot(p - a, ab) / np.dot(ab, ab), 0, 1))
    return float(np.linalg.norm(p - (a + t * ab)))


def on_road(field: dict[str, Any], x: float, y: float, margin: float = 0.0) -> bool:
    p = np.array([x, y])
    return any(
        _dist_to_segment(p, np.array(r["a"], float), np.array(r["b"], float)) < r["width_m"] / 2 + margin
        for r in field["roads"]
    )


def blocked(
    field: dict[str, Any],
    x: float,
    y: float,
    clearance: float,
    trees: list[tuple[str, float, float, float]] | None = None,
    road_ok: bool = False,
) -> bool:
    if not road_ok and on_road(field, x, y, margin=clearance / 3):
        return True
    for b in field["buildings"]:
        if math.hypot(x - b["xy"][0], y - b["xy"][1]) < 10 + clearance:
            return True
    lx, ly = field["launch"]["xy"]
    if math.hypot(x - lx, y - ly) < field["launch"]["keepout_m"] + clearance / 2:
        return True
    return any(math.hypot(x - tx, y - ty) < clearance for _, tx, ty, _ in trees or [])


def _uri(model: str) -> str:
    if model.startswith(("model://", "http")):
        return model
    return FUEL + model


def _include(name: str, model: str, x: float, y: float, z: float, yaw: float) -> str:
    return (
        f"    <include>\n      <name>{name}</name>\n      <uri>{_uri(model)}</uri>\n"
        f"      <pose>{x:.3f} {y:.3f} {z:.3f} 0 0 {yaw:.4f}</pose>\n      <static>true</static>\n"
        "    </include>\n"
    )


def world_sdf(scenario: dict[str, Any] | None = None, name: str = "search_field") -> str:
    field = load_field()
    o = field["origin"]
    wind = (scenario or {}).get("wind", {})
    parts = [
        f"""<?xml version="1.0" ?>
<sdf version="1.9">
  <world name="{name}">
    <physics name="1ms" type="ignore">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1.0</real_time_factor>
      <real_time_update_rate>0</real_time_update_rate>
    </physics>
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>
    <plugin filename="gz-sim-navsat-system" name="gz::sim::systems::NavSat"/>
    <scene>
      <ambient>0.6 0.6 0.6 1</ambient>
      <background>0.7 0.8 0.95 1</background>
      <sky></sky>
      <shadows>true</shadows>
    </scene>
    <spherical_coordinates>
      <latitude_deg>{o["lat"]}</latitude_deg>
      <longitude_deg>{o["lon"]}</longitude_deg>
      <elevation>{o["alt_m"]}</elevation>
      <heading_deg>0</heading_deg>
      <surface_model>EARTH_WGS84</surface_model>
    </spherical_coordinates>
    <light type="directional" name="sun">
      <cast_shadows>true</cast_shadows>
      <pose>0 0 100 0 0 0</pose>
      <diffuse>0.9 0.9 0.85 1</diffuse>
      <specular>0.3 0.3 0.3 1</specular>
      <direction>{(scenario or {}).get("sun_dir", "-0.4 0.3 -0.9")}</direction>
    </light>
    <model name="field">
      <static>true</static>
      <link name="ground">
        <collision name="c"><geometry><plane><normal>0 0 1</normal><size>400 400</size></plane></geometry></collision>
        <visual name="grass"><geometry><mesh><uri>{GEN}/field/meshes/ground.obj</uri></mesh></geometry></visual>
        <visual name="roads"><pose>0 0 0.02 0 0 0</pose><geometry><mesh><uri>{GEN}/field/meshes/roads.obj</uri></mesh></geometry></visual>
        <visual name="pad"><pose>0 0 0.03 0 0 0</pose><geometry><cylinder><radius>1.5</radius><length>0.02</length></cylinder></geometry>
          <material><ambient>0.3 0.3 0.3 1</ambient><diffuse>0.35 0.35 0.35 1</diffuse></material></visual>
      </link>
    </model>
"""
    ]
    for i, b in enumerate(field["buildings"]):
        parts.append(_include(f"building_{i}", b["model"], b["xy"][0], b["xy"][1], 0, b["yaw"]))
    for i, (m, x, y, yaw) in enumerate(tree_positions(field)):
        parts.append(_include(f"tree_{i}", m, x, y, 0, yaw))
    for obj in (scenario or {}).get("objects", []):
        parts.append(_include(obj["name"], obj["uri"], obj["x"], obj["y"], obj.get("z", 0.0), obj["yaw"]))
    lx, ly = field["launch"]["xy"]
    parts.append(
        f"""    <include>
      <uri>model://search_drone</uri>
      <pose degrees="true">{lx} {ly} 0.195 0 0 90</pose>
    </include>
"""
    )
    if wind:
        parts.append(f"    <!-- wind is simulated by SITL: {json.dumps(wind)} -->\n")
    parts.append("  </world>\n</sdf>\n")
    return "".join(parts)


def studio_sdf(model_uri: str, cam_dist: float, cam_pitch: float, cam_yaw: float) -> str:
    """A neutral backdrop with one object and an oblique camera, for reference photos."""
    cx = -cam_dist * math.cos(cam_pitch) * math.cos(cam_yaw)
    cy = -cam_dist * math.cos(cam_pitch) * math.sin(cam_yaw)
    cz = cam_dist * math.sin(cam_pitch)
    return f"""<?xml version="1.0" ?>
<sdf version="1.9">
  <world name="studio">
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <scene><ambient>0.7 0.7 0.7 1</ambient><background>0.85 0.85 0.85 1</background><shadows>true</shadows></scene>
    <light type="directional" name="sun">
      <cast_shadows>true</cast_shadows><pose>0 0 20 0 0 0</pose>
      <diffuse>0.9 0.9 0.9 1</diffuse><direction>-0.3 0.4 -0.9</direction>
    </light>
    <model name="floor"><static>true</static><link name="l">
      <visual name="v"><geometry><plane><normal>0 0 1</normal><size>60 60</size></plane></geometry>
        <material><ambient>0.55 0.52 0.48 1</ambient><diffuse>0.6 0.57 0.52 1</diffuse></material></visual>
    </link></model>
    <include><uri>{_uri(model_uri)}</uri><pose>0 0 0 0 0 0</pose><static>true</static></include>
    <model name="cam"><static>true</static>
      <pose>{cx:.3f} {cy:.3f} {cz:.3f} 0 {cam_pitch:.4f} {cam_yaw:.4f}</pose>
      <link name="l"><sensor name="c" type="camera">
        <camera><horizontal_fov>0.9</horizontal_fov><image><width>640</width><height>480</height></image>
        <clip><near>0.05</near><far>200</far></clip></camera>
        <always_on>1</always_on><update_rate>5</update_rate><topic>/studio/camera</topic>
      </sensor></link>
    </model>
  </world>
</sdf>
"""
