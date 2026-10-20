#!/usr/bin/env python3
"""Bridge Gazebo camera frames to a shared-memory directory.

Runs under the *system* Python (``/usr/bin/python3``) because the gz-transport bindings
are packaged for it, while the MCP server lives in its own venv. The server never imports
Gazebo; it only reads what this process writes, the same way it would read a real
camera's video stream. That keeps the backend boundary clean: nothing in the server can
query the simulator for object poses.

Output (atomically replaced on every frame):
    <out>/frame.rgb   raw RGB8 bytes, width*height*3
    <out>/frame.json  {"seq", "width", "height", "stamp_sim_s", "wall_time", "fx", "fy", "cx", "cy"}

Modes:
    frame_grabber.py --topic /search_drone/camera --out /dev/shm/drone_search
    frame_grabber.py --topic /studio/camera --once ref.png      # save one frame and exit
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

from gz.msgs10.camera_info_pb2 import CameraInfo
from gz.msgs10.image_pb2 import Image
from gz.transport13 import Node

_info: dict[str, float] = {}


def _on_info(msg: CameraInfo) -> None:
    k = list(msg.intrinsics.k)
    if len(k) == 9:
        _info.update(fx=k[0], fy=k[4], cx=k[2], cy=k[5])


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--topic", default="/search_drone/camera")
    p.add_argument("--out", default="/dev/shm/drone_search")
    p.add_argument("--once", help="write a single PNG to this path and exit")
    p.add_argument("--skip", type=int, default=3, help="--once: frames to skip (let lighting settle)")
    p.add_argument("--timeout", type=float, default=120.0)
    a = p.parse_args()

    node = Node()
    done = threading.Event()
    count = {"n": 0}

    def on_image(msg: Image) -> None:
        count["n"] += 1
        w, h = msg.width, msg.height
        if a.once:
            if count["n"] <= a.skip or done.is_set():
                return
            from PIL import Image as PILImage

            PILImage.frombytes("RGB", (w, h), msg.data).save(a.once)
            done.set()
            return
        os.makedirs(a.out, exist_ok=True)
        tmp_rgb = os.path.join(a.out, ".frame.rgb.tmp")
        tmp_js = os.path.join(a.out, ".frame.json.tmp")
        with open(tmp_rgb, "wb") as f:
            f.write(msg.data)
        meta = {
            "seq": count["n"],
            "width": w,
            "height": h,
            "stamp_sim_s": msg.header.stamp.sec + msg.header.stamp.nsec * 1e-9,
            "wall_time": time.time(),
            **_info,
        }
        with open(tmp_js, "w") as f:
            json.dump(meta, f)
        # rgb first, then json: a reader that sees a new json always finds a matching rgb
        os.replace(tmp_rgb, os.path.join(a.out, "frame.rgb"))
        os.replace(tmp_js, os.path.join(a.out, "frame.json"))

    # gz-sensors publishes intrinsics next to the image topic: /a/b/camera -> /a/b/camera_info
    node.subscribe(CameraInfo, a.topic.rsplit("/", 1)[0] + "/camera_info", _on_info)
    if not node.subscribe(Image, a.topic, on_image):
        print(f"[frame_grabber] cannot subscribe to {a.topic}", file=sys.stderr)
        return 2
    print(f"[frame_grabber] subscribed to {a.topic}", file=sys.stderr, flush=True)
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
