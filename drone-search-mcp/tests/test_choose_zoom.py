from server.mission import choose_zoom


def test_zooms_to_fill_half_the_frame_not_just_the_target_size() -> None:
    # 1.6 m candidate seen at 12 m by the calibrated sim camera (fx 939): 125 px at 1x.
    # 220 px alone would ask for 1.8x, below a wide/tele pair's 2x switch (hard-7008).
    assert choose_zoom(125.0, 960, 220.0, 4.0) > 3.5


def test_small_objects_get_full_zoom_and_large_ones_none() -> None:
    assert choose_zoom(20.0, 960, 220.0, 4.0) == 4.0
    assert choose_zoom(700.0, 960, 220.0, 4.0) == 1.0
