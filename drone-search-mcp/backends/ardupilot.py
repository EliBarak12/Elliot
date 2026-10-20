"""ArduPilot over MAVLink (pymavlink). Used for SITL today, for real ArduCopter later.

The same class talks to SITL and to hardware; what differs is the frame source and whether
the server lets it fly. Simulation is proven by the vehicle, never by the connection
string: ArduPilot SITL streams ``SIMSTATE`` and real firmware does not (the mavlink-mcp
approach). ``SimBackend`` in ``backends/sim.py`` wires this up for Gazebo.
"""

from __future__ import annotations

import bisect
import dataclasses
import math
import os
import threading
import time
from collections import deque
from typing import Any

import structlog

os.environ.setdefault("MAVLINK20", "1")  # gimbal/SIMSTATE messages need the v2 dialect
from pymavlink import mavutil  # noqa: E402

from backends.base import BackendError, DroneBackend, Frame, Telemetry
from backends.camera import FrameSource

log = structlog.get_logger(__name__)

mavutil.set_dialect("ardupilotmega")
M = mavutil.mavlink
COPTER_MODES = {
    "STABILIZE": 0,
    "ACRO": 1,
    "ALT_HOLD": 2,
    "AUTO": 3,
    "GUIDED": 4,
    "LOITER": 5,
    "RTL": 6,
    "CIRCLE": 7,
    "LAND": 9,
    "BRAKE": 17,
    "SMART_RTL": 21,
}
MODE_NAMES = {v: k for k, v in COPTER_MODES.items()}
# ArduPilot EKF_STATUS_REPORT flags we need before arming in GUIDED
EKF_REQUIRED = M.EKF_ATTITUDE | M.EKF_VELOCITY_HORIZ | M.EKF_POS_HORIZ_ABS | M.EKF_POS_VERT_ABS
POSITION_ONLY_MASK = 0b0000_1101_1111_1000  # use lat/lon/alt, ignore vel/acc/yaw
STREAMS_HZ = {
    M.MAVLINK_MSG_ID_GLOBAL_POSITION_INT: 20,
    M.MAVLINK_MSG_ID_ATTITUDE: 20,
    M.MAVLINK_MSG_ID_SYS_STATUS: 2,
    M.MAVLINK_MSG_ID_BATTERY_STATUS: 1,
    M.MAVLINK_MSG_ID_GPS_RAW_INT: 2,
    M.MAVLINK_MSG_ID_EKF_STATUS_REPORT: 2,
    M.MAVLINK_MSG_ID_HOME_POSITION: 0.5,
    M.MAVLINK_MSG_ID_SIMSTATE: 1,
    M.MAVLINK_MSG_ID_GIMBAL_DEVICE_ATTITUDE_STATUS: 10,
}


class ArduPilotBackend(DroneBackend):
    name = "ardupilot"

    def __init__(
        self,
        connection: str,
        frames: FrameSource | None,
        frame_clock_offset_s: float = 0.0,
    ) -> None:
        self.connection = connection
        self.frames = frames
        self.frame_clock_offset_s = frame_clock_offset_s
        self._mav: Any = None
        self._lock = threading.Lock()  # guards self._t and the history
        self._send_lock = threading.Lock()  # pymavlink writes are not thread-safe
        self._t = Telemetry()
        self._history: deque[tuple[float, Telemetry]] = deque(maxlen=400)
        self._acks: dict[int, tuple[int, float]] = {}
        self._ack_cv = threading.Condition()
        self._sim_seen_at = 0.0
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_msg_at = 0.0

    # ------------------------------------------------------------------ link
    def connect(self, timeout_s: float = 30.0) -> None:
        log.info("backend.connect.start", connection=self.connection)
        self._mav = mavutil.mavlink_connection(
            self.connection,
            source_system=255,
            source_component=M.MAV_COMP_ID_MISSIONPLANNER,
            autoreconnect=True,
        )
        hb = self._mav.wait_heartbeat(timeout=timeout_s)
        if hb is None:
            raise BackendError(f"no heartbeat from {self.connection} within {timeout_s:.0f}s")
        if hb.type not in (M.MAV_TYPE_QUADROTOR, M.MAV_TYPE_HEXAROTOR, M.MAV_TYPE_OCTOROTOR):
            raise BackendError(f"vehicle type {hb.type} is not a multirotor; refusing to fly it")
        self._stop.clear()
        for target in (self._reader, self._heartbeat):
            th = threading.Thread(target=target, daemon=True, name=target.__name__)
            th.start()
            self._threads.append(th)
        for msg_id, hz in STREAMS_HZ.items():
            self._command(M.MAV_CMD_SET_MESSAGE_INTERVAL, msg_id, 1e6 / hz, wait=False)
        # wait for a first position so telemetry() is meaningful right away
        t0 = time.time()
        while time.time() - t0 < timeout_s and self.telemetry().lat is None:
            time.sleep(0.1)
        log.info("backend.connect.complete", sysid=self._mav.target_system)

    def close(self) -> None:
        self._stop.set()
        for th in self._threads:
            th.join(timeout=2)
        self._threads.clear()
        if self._mav is not None:
            self._mav.close()
            self._mav = None
        log.info("backend.closed")

    def _heartbeat(self) -> None:
        # The autopilot's GCS failsafe (FS_GCS_ENABLE) triggers RTL if these stop: if this
        # server dies mid-mission the vehicle comes home on its own.
        while not self._stop.wait(1.0):
            try:
                with self._send_lock:
                    self._mav.mav.heartbeat_send(M.MAV_TYPE_GCS, M.MAV_AUTOPILOT_INVALID, 0, 0, 0)
            except OSError as exc:
                log.warning("backend.heartbeat.error", error=str(exc))

    def _reader(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._mav.recv_match(blocking=True, timeout=0.5)
            except (OSError, ValueError) as exc:  # link hiccup; autoreconnect handles TCP
                log.warning("backend.reader.error", error=str(exc))
                time.sleep(0.5)
                continue
            if msg is None:
                continue
            try:
                self._handle(msg)
            except Exception:  # one malformed message must not kill telemetry
                log.error("backend.reader.handle_failed", msg_type=msg.get_type(), exc_info=True)

    def _handle(self, msg: Any) -> None:
        mt = msg.get_type()
        if msg.get_srcSystem() != self._mav.target_system:
            return
        now = time.time()
        self._last_msg_at = now
        with self._lock:
            t = self._t
            t.wall_time = now
            if mt == "HEARTBEAT" and msg.get_srcComponent() == M.MAV_COMP_ID_AUTOPILOT1:
                t.armed = bool(msg.base_mode & M.MAV_MODE_FLAG_SAFETY_ARMED)
                t.mode = MODE_NAMES.get(msg.custom_mode, f"MODE_{msg.custom_mode}")
            elif mt == "GLOBAL_POSITION_INT":
                t.lat, t.lon = msg.lat / 1e7, msg.lon / 1e7
                t.alt_rel_m, t.alt_amsl_m = msg.relative_alt / 1000, msg.alt / 1000
                t.vn_ms, t.ve_ms, t.vd_ms = msg.vx / 100, msg.vy / 100, msg.vz / 100
                t.heading_deg = msg.hdg / 100 if msg.hdg != 65535 else t.heading_deg
                t.time_boot_s = msg.time_boot_ms / 1000
                self._history.append((t.time_boot_s, dataclasses.replace(t, status_text=[])))
            elif mt == "ATTITUDE":
                t.roll_rad, t.pitch_rad, t.yaw_rad = msg.roll, msg.pitch, msg.yaw
                t.roll_rate, t.pitch_rate, t.yaw_rate = msg.rollspeed, msg.pitchspeed, msg.yawspeed
            elif mt == "SYS_STATUS":
                if msg.battery_remaining >= 0:
                    t.battery_pct = float(msg.battery_remaining)
                t.battery_v = msg.voltage_battery / 1000 if msg.voltage_battery > 0 else None
                t.current_a = msg.current_battery / 100 if msg.current_battery >= 0 else None
            elif mt == "GPS_RAW_INT":
                t.gps_fix, t.satellites = msg.fix_type, msg.satellites_visible
            elif mt == "EKF_STATUS_REPORT":
                t.ekf_ok = (msg.flags & EKF_REQUIRED) == EKF_REQUIRED
            elif mt == "HOME_POSITION":
                t.home_lat, t.home_lon = msg.latitude / 1e7, msg.longitude / 1e7
                t.home_alt_amsl_m = msg.altitude / 1000
            elif mt == "SIMSTATE":
                self._sim_seen_at = now
            elif mt == "GIMBAL_DEVICE_ATTITUDE_STATUS":
                w, x, y, z = msg.q
                t.gimbal_pitch_deg = math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))))
                t.gimbal_yaw_deg = math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))
            elif mt == "STATUSTEXT":
                t.status_text = (t.status_text + [msg.text])[-8:]
        if mt == "COMMAND_ACK":
            with self._ack_cv:
                self._acks[msg.command] = (msg.result, now)
                self._ack_cv.notify_all()

    # ------------------------------------------------------------- commands
    def _command(self, cmd: int, *params: float, wait: bool = True, timeout_s: float = 3.0, retries: int = 2) -> int:
        p = list(params) + [0.0] * (7 - len(params))
        for attempt in range(retries + 1):
            sent_at = time.time()
            with self._send_lock:
                self._mav.mav.command_long_send(self._mav.target_system, self._mav.target_component, cmd, attempt, *p)
            if not wait:
                return M.MAV_RESULT_ACCEPTED

            def acked(t: float = sent_at) -> bool:
                return cmd in self._acks and self._acks[cmd][1] >= t

            with self._ack_cv:
                ok = self._ack_cv.wait_for(acked, timeout_s)
                if ok:
                    return self._acks[cmd][0]
        raise BackendError(f"no COMMAND_ACK for command {cmd} after {retries + 1} attempts")

    def set_mode(self, mode: str, timeout_s: float = 5.0) -> None:
        mode_id = COPTER_MODES[mode]
        res = self._command(M.MAV_CMD_DO_SET_MODE, M.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, mode_id)
        if res != M.MAV_RESULT_ACCEPTED:
            raise BackendError(f"vehicle rejected mode {mode} (MAV_RESULT {res})")
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            if self.telemetry().mode == mode:
                return
            time.sleep(0.1)
        raise BackendError(f"mode did not change to {mode} within {timeout_s:.0f}s")

    def telemetry(self) -> Telemetry:
        with self._lock:
            return dataclasses.replace(self._t, status_text=list(self._t.status_text))

    def link_age_s(self) -> float:
        return time.time() - self._last_msg_at if self._last_msg_at else float("inf")

    def is_simulation(self) -> bool:
        return self._sim_seen_at > 0 and time.time() - self._sim_seen_at < 15

    def arm_and_takeoff(self, alt_m: float) -> None:
        log.info("backend.takeoff.start", alt_m=alt_m)
        t0 = time.time()
        while not self.telemetry().ekf_ok:
            if time.time() - t0 > 90:
                raise BackendError("EKF/GPS not ready after 90s; cannot arm")
            time.sleep(0.5)
        self.set_mode("GUIDED")
        last = None
        while time.time() - t0 < 120:
            res = self._command(M.MAV_CMD_COMPONENT_ARM_DISARM, 1)
            if res == M.MAV_RESULT_ACCEPTED:
                break
            last = res
            time.sleep(1.0)  # pre-arm checks settle a few seconds after EKF is happy
        else:
            raise BackendError(f"arming refused (MAV_RESULT {last}): {self.telemetry().status_text[-3:]}")
        res = self._command(M.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, math.nan, 0, 0, alt_m)
        if res != M.MAV_RESULT_ACCEPTED:
            raise BackendError(f"takeoff rejected (MAV_RESULT {res})")
        log.info("backend.takeoff.commanded", alt_m=alt_m)

    def goto(self, lat: float, lon: float, alt_rel_m: float, speed_ms: float | None = None) -> None:
        if self.telemetry().mode != "GUIDED":
            self.set_mode("GUIDED")
        if speed_ms is not None:
            self._command(M.MAV_CMD_DO_CHANGE_SPEED, 1, speed_ms, -1)
        with self._send_lock:
            self._mav.mav.set_position_target_global_int_send(
                0,
                self._mav.target_system,
                self._mav.target_component,
                M.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                POSITION_ONLY_MASK,
                int(lat * 1e7),
                int(lon * 1e7),
                alt_rel_m,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            )

    def hold(self) -> None:
        t = self.telemetry()
        if t.lat is None or t.alt_rel_m is None:
            self.set_mode("BRAKE")
            return
        self.goto(t.lat, t.lon, t.alt_rel_m)  # type: ignore[arg-type]

    def return_to_launch(self) -> None:
        self.set_mode("RTL")

    def land(self) -> None:
        self.set_mode("LAND")

    def emergency_stop(self, kill_motors: bool) -> None:
        # Fire-and-forget on purpose: no ack wait, no mode polling, no shared lock but the
        # socket write. Sent twice in case one datagram is dropped.
        for _ in range(2):
            with self._send_lock:
                if kill_motors:
                    self._mav.mav.command_long_send(
                        self._mav.target_system,
                        self._mav.target_component,
                        M.MAV_CMD_COMPONENT_ARM_DISARM,
                        0,
                        0,
                        21196,
                        0,
                        0,
                        0,
                        0,
                        0,
                    )
                else:
                    self._mav.mav.command_long_send(
                        self._mav.target_system,
                        self._mav.target_component,
                        M.MAV_CMD_DO_SET_MODE,
                        0,
                        M.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                        COPTER_MODES["BRAKE"],
                        0,
                        0,
                        0,
                        0,
                        0,
                    )
        log.warning("backend.emergency_stop", kill_motors=kill_motors)

    def set_gimbal_nadir(self) -> None:
        self._command(M.MAV_CMD_DO_MOUNT_CONTROL, -90, 0, 0, 0, 0, 0, M.MAV_MOUNT_MODE_MAVLINK_TARGETING)

    # ---------------------------------------------------------------- frames
    def pose_at(self, t_vehicle: float, max_gap_s: float = 0.25) -> Telemetry | None:
        """Vehicle state at a vehicle-clock time, linearly interpolated."""
        with self._lock:
            hist = list(self._history)
        if not hist:
            return None
        times = [h[0] for h in hist]
        i = bisect.bisect_left(times, t_vehicle)
        if i == 0:
            return hist[0][1] if times[0] - t_vehicle <= max_gap_s else None
        if i == len(hist):
            return hist[-1][1] if t_vehicle - times[-1] <= max_gap_s else None
        (t0, a), (t1, b) = hist[i - 1], hist[i]
        if t1 - t0 > 2 * max_gap_s:
            return None
        w = (t_vehicle - t0) / (t1 - t0) if t1 > t0 else 0.0

        def lerp(x: float | None, y: float | None) -> float | None:
            return None if x is None or y is None else x + (y - x) * w

        dyaw = (b.yaw_rad - a.yaw_rad + math.pi) % (2 * math.pi) - math.pi
        return dataclasses.replace(
            a,
            lat=lerp(a.lat, b.lat),
            lon=lerp(a.lon, b.lon),
            alt_rel_m=lerp(a.alt_rel_m, b.alt_rel_m),
            roll_rad=a.roll_rad + (b.roll_rad - a.roll_rad) * w,
            pitch_rad=a.pitch_rad + (b.pitch_rad - a.pitch_rad) * w,
            yaw_rad=a.yaw_rad + dyaw * w,
            time_boot_s=t_vehicle,
        )

    def latest_frame(self, max_age_s: float = 2.0) -> Frame | None:
        if self.frames is None:
            return None
        raw = self.frames.read()
        if raw is None or time.time() - raw.wall_time > max_age_s:
            return None
        pose = self.pose_at(raw.stamp_s + self.frame_clock_offset_s)
        if pose is None:
            return None
        return Frame(raw.image, raw.camera, raw.seq, raw.stamp_s, raw.wall_time, pose)
