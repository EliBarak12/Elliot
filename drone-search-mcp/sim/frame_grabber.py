#!/usr/bin/env python3
"""Bridge Gazebo camera frames to a shared-memory directory, optionally degraded to
real-world quality.

Runs under the *system* Python (``/usr/bin/python3``) because the gz-transport bindings
are packaged for it, while the MCP server lives in its own venv. The server never imports
Gazebo; it only reads what this process writes, the same way it would read a real
camera's video stream, so nothing in the server can query the simulator for object poses.

Output (atomically replaced on every frame):
    <out>/frame.rgb | frame.jpg   raw RGB8 (ideal mode) or JPEG (realism mode)
    <out>/frame.json  {"seq", "width", "height", "stamp_sim_s", "wall_time", "encoding", [fx, fy, cx, cy]}

In realism mode (``--realism profile.json``, see sim/realism.py) frames are distorted,
blurred, noisy and JPEG-compressed, delivered late with jitter, sometimes dropped, and
stamped with their *arrival* time. Intrinsics are not published: the server must use its
measured calibration, as with a real camera.

Modes:
    frame_grabber.py --topic /search_drone/camera --out /dev/shm/drone_search [--realism r.json]
    frame_grabber.py --topic /studio/camera --once ref.png      # save one frame and exit
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import random
import sys
import threading
import time

from gz.msgs10.camera_info_pb2 import CameraInfo
from gz.msgs10.clock_pb2 import Clock
from gz.msgs10.image_pb2 import Image
from gz.msgs10.pose_v_pb2 import Pose_V
from gz.transport13 import Node

_info: dict[str, float] = {}


def _on_info(msg: CameraInfo) -> None:
    k = list(msg.intrinsics.k)
    if len(k) == 9:
        _info.update(fx=k[0], fy=k[4], cx=k[2], cy=k[5])


class ZoomControl:
    """Camera zoom, driven like a real camera's control API.

    The server writes ``<out>/control.json`` {"zoom": Z}; we forward it to Gazebo's
    CameraZoomPlugin and report the zoom each frame was taken at (as a real camera reports
    its zoom state). Zoom is the focal-length ratio to the base lens; the plugin instead takes
    a FOV ratio against a fixed 2.0 rad, so we convert.
    """

    PLUGIN_REF_HFOV = 2.0

    def __init__(self, node: Node, out: str, base_hfov: float) -> None:
        self.node = node
        self.path = os.path.join(out, "control.json")
        self.base_hfov = base_hfov
        self.mtime = 0.0
        self.cmd = 1.0
        self.prev = 1.0
        self.cmd_at = 0.0
        self.pub = None
        self.base_fx: float | None = None
        self.initialised = False

    def poll(self) -> None:
        if not self.initialised:
            # The plugin slews to its own 2.0 rad default FOV on load (it took the 1.2 rad
            # lens to a 0.35x focal length and broke every projection); pin zoom 1 first.
            if self._publish(1.0):
                self.initialised = True
                self.cmd_at = time.time()
            return
        try:
            m = os.path.getmtime(self.path)
        except OSError:
            return
        if m == self.mtime:
            return
        self.mtime = m
        try:
            with open(self.path) as f:
                z = float(json.load(f).get("zoom", 1.0))
        except (OSError, ValueError):
            return
        z = max(1.0, z)
        prev = self.current(time.time())
        if self._publish(z):
            self.prev, self.cmd, self.cmd_at = prev, z, time.time()

    def _publish(self, z: float) -> bool:
        if self.pub is None:
            from gz.msgs10.double_pb2 import Double

            topic = next((t for t in self.node.topic_list() if t.endswith("/zoom/cmd_zoom")), None)
            if topic is None:
                return False
            self.pub = self.node.advertise(topic, Double)
            self._msg = Double
            time.sleep(0.5)  # let the subscription connect before the first message
        msg = self._msg()
        # zoom = focal-length ratio; the plugin takes 2.0 rad / target FOV
        target_hfov = 2 * math.atan(math.tan(self.base_hfov / 2) / z)
        msg.data = self.PLUGIN_REF_HFOV / target_hfov
        self.pub.publish(msg)
        return True

    def current(self, now: float) -> float:
        """Zoom in effect: from the published intrinsics when they track the zoom, else the
        commanded value once the lens has had time to move."""
        # (gz camera_info does not follow the zoom plugin, so the commanded value it is)
        if now - self.cmd_at < 1.5:
            return self.prev  # still slewing; report the old value
        return self.cmd


def _write(out: str, payload: bytes, ext: str, meta: dict) -> None:
    os.makedirs(out, exist_ok=True)
    tmp_img = os.path.join(out, f".frame.{ext}.tmp")
    tmp_js = os.path.join(out, ".frame.json.tmp")
    with open(tmp_img, "wb") as f:
        f.write(payload)
    with open(tmp_js, "w") as f:
        json.dump(meta, f)
    # image first, then json: a reader that sees a new json always finds a matching image
    os.replace(tmp_img, os.path.join(out, f"frame.{ext}"))
    os.replace(tmp_js, os.path.join(out, "frame.json"))


class DroneMotion:
    """Drone velocity from Gazebo poses (simulator side only, for motion blur)."""

    def __init__(self) -> None:
        self.prev: tuple[float, float, float, float] | None = None
        self.vel = (0.0, 0.0)
        self.yaw = 0.0
        self.alt = 20.0

    def on_poses(self, msg: Pose_V) -> None:
        t = msg.header.stamp.sec + msg.header.stamp.nsec * 1e-9
        for p in msg.pose:
            if p.name != "search_drone":
                continue
            q = p.orientation
            self.yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
            self.alt = max(p.position.z, 0.5)
            if self.prev is not None and t > self.prev[0]:
                dt = t - self.prev[0]
                self.vel = ((p.position.x - self.prev[1]) / dt, (p.position.y - self.prev[2]) / dt)
            self.prev = (t, p.position.x, p.position.y, p.position.z)

    def image_velocity(self, fx: float) -> tuple[float, float]:
        ve, vn = self.vel
        fwd = ve * math.cos(self.yaw) + vn * math.sin(self.yaw)
        right = ve * math.sin(self.yaw) - vn * math.cos(self.yaw)
        # ground slides opposite to the motion: forward flight moves it down the image
        return -right * fx / self.alt, fwd * fx / self.alt


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--topic", default="/search_drone/camera")
    p.add_argument("--out", default="/dev/shm/drone_search")
    p.add_argument("--world", default="search_field")
    p.add_argument("--realism", help="JSON realism profile (sim/realism.py); omit for ideal frames")
    p.add_argument("--once", help="write a single PNG to this path and exit")
    p.add_argument("--skip", type=int, default=3, help="--once: frames to skip (let lighting settle)")
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--base-hfov", type=float, default=1.2, help="camera FOV at zoom 1 (rad)")
    a = p.parse_args()

    node = Node()
    done = threading.Event()
    count = {"n": 0}
    profile = None
    degrader = None
    motion = DroneMotion()
    clock = {"sim": 0.0}
    dropped = {"n": 0}
    queue: collections.deque = collections.deque()
    qlock = threading.Lock()
    if a.realism:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from realism import Degrader, RealismProfile

        with open(a.realism) as f:
            profile = RealismProfile.from_dict(json.load(f))
        if not profile.enabled:
            profile = None
        rng = random.Random(1)

    def on_image(msg: Image) -> None:
        nonlocal degrader
        count["n"] += 1
        if zoom is not None:
            zoom.poll()
        zoom_now = zoom.current(time.time()) if zoom is not None else 1.0
        w, h = msg.width, msg.height
        stamp = msg.header.stamp.sec + msg.header.stamp.nsec * 1e-9
        if a.once:
            if count["n"] <= a.skip or done.is_set():
                return
            from PIL import Image as PILImage

            PILImage.frombytes("RGB", (w, h), msg.data).save(a.once)
            done.set()
            return
        if profile is None:
            meta = {
                "seq": count["n"],
                "width": w,
                "height": h,
                "stamp_sim_s": stamp,
                "wall_time": time.time(),
                "encoding": "rgb",
                "zoom": zoom_now,
                **({} if zoom_now != 1.0 else _info),
            }
            _write(a.out, msg.data, "rgb", meta)
            return
        if rng.random() < profile.drop_prob:
            return
        if clock["sim"] and stamp < clock["sim"] - 0.3:
            # behind the camera rate: drop instead of queueing, like a real video link.
            # (Queued frames made latency grow without bound over a mission: frames
            # arrived >10 s late and were paired with the wrong pose.)
            dropped["n"] += 1
            return
        import numpy as np

        if degrader is None:
            fx = _info.get("fx", w / 2 / math.tan(0.6))
            degrader = Degrader(profile, w, h, fx, seed=7)
        rgb = np.frombuffer(msg.data, np.uint8).reshape(h, w, 3)
        jpeg = degrader.apply(rgb, motion.image_velocity(degrader.fx), motion.alt)
        release = stamp + max(0.0, rng.gauss(profile.latency_s, profile.latency_jitter_s))
        with qlock:
            queue.append((release, count["n"], w, h, jpeg, zoom_now))

    def on_clock(msg: Clock) -> None:
        clock["sim"] = msg.sim.sec + msg.sim.nsec * 1e-9

    def releaser() -> None:
        # deliver each frame once the simulated pipeline latency has elapsed (in sim time,
        # so it scales with the lockstep real-time factor), stamped with its arrival time
        while True:
            item = None
            with qlock:
                if queue and queue[0][0] <= clock["sim"]:
                    item = queue.popleft()
            if item is None:
                time.sleep(0.005)
                continue
            release, seq, w, h, jpeg, zoom_at_capture = item
            meta = {
                "seq": seq,
                "width": w,
                "height": h,
                # arrival = capture + modelled pipeline latency (what a companion computer
                # stamps); processing time on this host must not leak into it
                "stamp_sim_s": release,
                "wall_time": time.time(),
                "encoding": "jpeg",
                "zoom": zoom_at_capture,
            }
            _write(a.out, jpeg, "jpg", meta)

    zoom = None if a.once else ZoomControl(node, a.out, a.base_hfov)
    # gz-sensors publishes intrinsics next to the image topic: /a/b/camera -> /a/b/camera_info
    node.subscribe(CameraInfo, a.topic.rsplit("/", 1)[0] + "/camera_info", _on_info)
    if profile is not None:
        node.subscribe(Pose_V, f"/world/{a.world}/dynamic_pose/info", motion.on_poses)
        node.subscribe(Clock, f"/world/{a.world}/clock", on_clock)
        threading.Thread(target=releaser, daemon=True).start()
    if not node.subscribe(Image, a.topic, on_image):
        print(f"[frame_grabber] cannot subscribe to {a.topic}", file=sys.stderr)
        return 2
    print(
        f"[frame_grabber] subscribed to {a.topic} (realism={'on' if profile else 'off'})", file=sys.stderr, flush=True
    )
    if a.once:
        ok = done.wait(a.timeout)
        if not ok:
            print("[frame_grabber] timed out waiting for a frame", file=sys.stderr)
        return 0 if ok else 1
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
