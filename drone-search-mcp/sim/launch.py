"""Start / stop the simulator stack: Gazebo (headless) + ArduCopter SITL + frame bridge.

    python sim/launch.py up [--scenario scenarios/runs/<id>/scenario.json] [--speedup 1]
    python sim/launch.py down
    python sim/launch.py check        # heartbeat on the spare MAVLink port + a fresh camera frame

The scenario file is the *public* half of a scenario (world objects, wind). Ground truth is
written elsewhere by scenarios/generate.py and is never passed to this launcher.
PIDs and logs go to $DSM_RUN_DIR.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from sim.world import load_field, world_sdf  # noqa: E402

RUN = Path(os.environ.get("DSM_RUN_DIR", "/tmp/drone_search_run"))
FRAMES = Path(os.environ.get("DSM_FRAME_DIR", "/dev/shm/drone_search"))
SIM_HOME = Path(os.environ.get("DSM_SIM_HOME", "/opt/sim"))
SYS_PY = os.environ.get("DSM_SYS_PYTHON", "/usr/bin/python3.12")
PARAMS = SIM_HOME / "ardupilot" / "Tools" / "autotest" / "default_params"


def _start(name: str, cmd: list[str], cwd: Path | None = None) -> int:
    log = open(RUN / f"{name}.log", "w")  # noqa: SIM115 - handed to the child process
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        start_new_session=True,
    )
    (RUN / f"{name}.pid").write_text(str(proc.pid))
    return proc.pid


def down() -> None:
    for pidf in RUN.glob("*.pid") if RUN.exists() else []:
        with contextlib.suppress(ProcessLookupError, ValueError, PermissionError):
            os.killpg(int(pidf.read_text()), signal.SIGTERM)
        pidf.unlink(missing_ok=True)
    # gz forks a separate server process; make sure nothing of ours survives
    subprocess.run(["pkill", "-f", "gz sim -s"], check=False)
    subprocess.run(["pkill", "-x", "arducopter"], check=False)
    # a lingering SITL keeps 5760 bound and the next one exits with "bind failed"
    for _ in range(40):
        if not any("LISTEN" in _port_states(p) for p in (5760, 5762)):
            break
        time.sleep(0.25)
    else:
        subprocess.run(["pkill", "-9", "-x", "arducopter"], check=False)
        time.sleep(1.0)


def _port_states(port: int) -> set[str]:
    """TCP states using a local port, read from /proc (probing with connect() would itself
    leave server-side TIME_WAITs behind once SITL is killed, blocking the next bind)."""
    states = {"01": "ESTABLISHED", "06": "TIME_WAIT", "0A": "LISTEN"}
    out: set[str] = set()
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(f).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            cols = line.split()
            if int(cols[1].rsplit(":", 1)[1], 16) == port:
                out.add(states.get(cols[3], cols[3]))
    return out


def wait_frame(timeout: float, after: float = 0.0) -> dict | None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            meta = json.loads((FRAMES / "frame.json").read_text())
            if meta["wall_time"] > after:
                return meta
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    return None


def up(scenario_path: Path | None, speedup: float) -> int:
    down()
    RUN.mkdir(parents=True, exist_ok=True)
    scenario = json.loads(scenario_path.read_text()) if scenario_path else None
    world = RUN / "world.sdf"
    world.write_text(world_sdf(scenario))
    if FRAMES.exists():
        for f in FRAMES.iterdir():
            f.unlink()

    t0 = time.time()
    _start("gazebo", ["gz", "sim", "-s", "-r", "--headless-rendering", str(world)])
    grab = [SYS_PY, str(HERE / "frame_grabber.py"), "--out", str(FRAMES)]
    realism = (scenario or {}).get("realism") or {}
    if realism.get("camera"):
        (RUN / "realism.json").write_text(json.dumps(realism["camera"]))
        grab += ["--realism", str(RUN / "realism.json")]
    _start("frames", grab)

    parm = RUN / "scenario.parm"
    extra = []
    wind = (scenario or {}).get("wind") or {}
    if wind:
        extra += [
            f"SIM_WIND_SPD {wind.get('speed_ms', 0)}",
            f"SIM_WIND_DIR {wind.get('dir_deg', 0)}",
            f"SIM_WIND_TURB {wind.get('turbulence', 0)}",
        ]
    nav = realism.get("nav") or {}
    if nav:
        extra += [
            f"SIM_GPS1_NOISE {nav.get('gps_noise_m', 0)}",
            f"SIM_BARO_RND {nav.get('baro_noise_m', 0)}",
            f"SIM_GPS1_DRFTALT {nav.get('gps_alt_drift_m', 0)}",
            # sim_gps_drift.lua: horizontal bias random walk
            f"SCR_USER1 {nav.get('gps_bias_sigma_m', 0)}",
            f"SCR_USER2 {nav.get('gps_bias_tau_s', 120)}",
            f"SCR_USER3 {nav.get('seed', 1)}",
        ]
    parm.write_text("\n".join(extra) + "\n")
    o = load_field()["origin"]
    defaults = ",".join(
        str(p)
        for p in (
            PARAMS / "copter.parm",
            PARAMS / "gazebo-iris.parm",
            HERE / "params" / "search_drone.parm",
            parm,
        )
    )
    # SITL does not set SO_REUSEADDR: wait out TIME_WAITs from a client killed with it
    for _ in range(140):
        if not any(_port_states(p) for p in (5760, 5762, 5763)):
            break
        time.sleep(0.5)
    else:
        print("[sim] MAVLink ports still busy after 70 s:", _port_states(5760))
        return 1
    sitl_dir = RUN / "sitl"
    sitl_dir.mkdir(exist_ok=True)
    # ArduPilot SITL loads Lua scripts from ./scripts relative to its working directory
    scripts = sitl_dir / "scripts"
    scripts.mkdir(exist_ok=True)
    for lua in (HERE / "scripts").glob("*.lua"):
        (scripts / lua.name).write_text(lua.read_text())
    _start(
        "sitl",
        [
            # wrapped in sh so the log records how SITL exited
            "sh",
            "-c",
            '"$@"; echo "[sitl] exited with status $?"',
            "sh",
            str(SIM_HOME / "arducopter"),
            "--model",
            "JSON:127.0.0.1",
            "--speedup",
            str(speedup),
            "--defaults",
            defaults,
            "-I0",
            # serial0 defaults to tcp:0:wait, which blocks boot until a client connects
            "--serial0",
            "tcp:0",
            "--wipe",
            "--home",
            f"{o['lat']},{o['lon']},{o['alt_m']},0",
        ],
        cwd=sitl_dir,
    )
    # SITL listens on 5760 (server) and 5762 (eval monitor); never connect to 5760 here.
    for _ in range(240):
        if "LISTEN" in _port_states(5762):
            break
        time.sleep(0.5)
    else:
        print("[sim] SITL did not open its MAVLink ports; see", RUN / "sitl.log")
        return 1
    meta = wait_frame(120, after=t0)
    if meta is None:
        print("[sim] no camera frame within 120 s; see", RUN / "gazebo.log", RUN / "frames.log")
        return 1
    (RUN / "scenario_path").write_text(str(scenario_path or ""))
    print(
        f"[sim] up in {time.time() - t0:.1f}s: camera {meta['width']}x{meta['height']}, "
        f"MAVLink tcp:127.0.0.1:5760 (server) / 5762 (monitor)"
    )
    return 0


def check(timeout: float = 90.0) -> int:
    from pymavlink import mavutil

    m = mavutil.mavlink_connection("tcp:127.0.0.1:5762", source_system=250)
    hb = m.wait_heartbeat(timeout=timeout)
    if hb is None:
        print("[sim] no heartbeat on 5762")
        return 1
    m.mav.request_data_stream_send(m.target_system, m.target_component, 0, 4, 1)
    sim = m.recv_match(type="SIMSTATE", blocking=True, timeout=15)
    meta = wait_frame(10, after=time.time() - 5)
    print(
        f"[sim] heartbeat ok (type={hb.type}), SIMSTATE={'yes' if sim else 'no'}, "
        f"fresh frame={'yes seq=' + str(meta['seq']) if meta else 'no'}"
    )
    return 0 if (sim and meta) else 1


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("up")
    u.add_argument("--scenario", type=Path)
    u.add_argument("--speedup", type=float, default=1.0)
    sub.add_parser("down")
    sub.add_parser("check")
    a = p.parse_args()
    if a.cmd == "up":
        return up(a.scenario, a.speedup)
    if a.cmd == "down":
        down()
        return 0
    return check()


if __name__ == "__main__":
    sys.exit(main())
