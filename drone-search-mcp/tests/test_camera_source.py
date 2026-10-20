import json
from pathlib import Path

import cv2
import numpy as np

from backends.camera import ShmFrameSource, load_calibration


def test_jpeg_frames_use_measured_calibration(tmp_path: Path) -> None:
    img = np.zeros((48, 64, 3), np.uint8)
    img[:, :, 0] = 200
    cv2.imwrite(str(tmp_path / "frame.jpg"), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    (tmp_path / "frame.json").write_text(
        json.dumps({"seq": 3, "width": 64, "height": 48, "stamp_sim_s": 1.5, "wall_time": 0.0, "encoding": "jpeg"})
    )
    cal_p = tmp_path / "cal.json"
    cal_p.write_text(
        json.dumps({"fx": 50.0, "fy": 50.0, "cx": 32.0, "cy": 24.0, "k1": -0.05, "frame_clock_offset_s": -0.3})
    )
    cal = load_calibration(cal_p)
    f = ShmFrameSource(tmp_path, calibration=cal).read()
    assert f is not None and f.seq == 3 and f.image.shape == (48, 64, 3)
    assert f.image[10, 10, 0] > 150  # RGB order preserved
    assert f.camera.fx == 50.0 and f.camera.k1 == -0.05
    assert load_calibration(tmp_path / "missing.json") is None


def test_rgb_frames_fall_back_to_published_intrinsics(tmp_path: Path) -> None:
    np.zeros((4, 6, 3), np.uint8).tofile(tmp_path / "frame.rgb")
    (tmp_path / "frame.json").write_text(
        json.dumps(
            {
                "seq": 1,
                "width": 6,
                "height": 4,
                "stamp_sim_s": 0.0,
                "wall_time": 0.0,
                "fx": 5.0,
                "fy": 5.0,
                "cx": 3.0,
                "cy": 2.0,
            }
        )
    )
    f = ShmFrameSource(tmp_path).read()
    assert f is not None and f.camera.fx == 5.0 and f.camera.k1 == 0.0
    # truncated file: keep the previous frame instead of returning garbage
    np.zeros(5, np.uint8).tofile(tmp_path / "frame.rgb")
    (tmp_path / "frame.json").write_text(
        json.dumps({"seq": 2, "width": 6, "height": 4, "stamp_sim_s": 0.0, "wall_time": 0.0})
    )
    assert ShmFrameSource(tmp_path).read() is None
