"""Tests for scripts/open_studio.py — the auto-open-browser helper.

The script must:
  - Skip silently when disabled (env var) or headless (no $DISPLAY on Linux)
  - Poll Studio's URL until it responds, with a bounded timeout
  - Open the user's default browser on success
  - Never raise — every error path exits 0 so it doesn't break `make dev`
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "open_studio.py"


@pytest.fixture()
def open_studio(monkeypatch: pytest.MonkeyPatch):
    """Import scripts/open_studio.py fresh for each test, with a clean env."""
    # Clear any caller env vars that would skew test outcomes
    for var in (
        "ELLIOT_OPEN_BROWSER",
        "ELLIOT_STUDIO_URL",
        "ELLIOT_BROWSER_TIMEOUT",
        "ELLIOT_BROWSER_POLL_INTERVAL",
        "DISPLAY",
    ):
        monkeypatch.delenv(var, raising=False)
    # Pretend we're on a desktop so is_enabled() defaults to True
    monkeypatch.setenv("DISPLAY", ":0")

    # Force a fresh import so module-level config picks up the env we just set
    spec = importlib.util.spec_from_file_location("_open_studio_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_open_studio_test"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("_open_studio_test", None)


def test_disabled_when_elliot_open_browser_is_zero(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_OPEN_BROWSER", "0")
    monkeypatch.setenv("DISPLAY", ":0")
    spec = importlib.util.spec_from_file_location("_disabled_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.is_enabled() is False


@pytest.mark.parametrize("val", ["false", "no", "OFF", "0"])
def test_disabled_for_truthy_off_values(monkeypatch: pytest.MonkeyPatch, val: str):
    monkeypatch.setenv("ELLIOT_OPEN_BROWSER", val)
    monkeypatch.setenv("DISPLAY", ":0")
    spec = importlib.util.spec_from_file_location("_off_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.is_enabled() is False


def test_disabled_on_headless_linux(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("ELLIOT_OPEN_BROWSER", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    spec = importlib.util.spec_from_file_location("_headless_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.is_enabled() is False


def test_enabled_with_display(open_studio):
    assert open_studio.is_enabled() is True


def test_studio_is_up_returns_false_on_connection_error(open_studio):
    """A genuine unreachable URL must return False, not raise."""
    assert open_studio.studio_is_up("http://127.0.0.1:1/never") is False


def test_wait_for_studio_returns_false_after_timeout(open_studio):
    """If studio_is_up always says no, the poll loop must time out cleanly."""
    with patch.object(open_studio, "studio_is_up", return_value=False):
        assert (
            open_studio.wait_for_studio("http://example", timeout_s=0.05, interval_s=0.01) is False
        )


def test_wait_for_studio_returns_true_when_studio_responds(open_studio):
    with patch.object(open_studio, "studio_is_up", return_value=True):
        assert open_studio.wait_for_studio("http://example", timeout_s=1.0, interval_s=0.01) is True


def test_main_opens_browser_when_enabled_and_studio_responds(open_studio):
    with (
        patch.object(open_studio, "is_enabled", return_value=True),
        patch.object(open_studio, "wait_for_studio", return_value=True),
        patch.object(open_studio.webbrowser, "open") as wb_open,
    ):
        exit_code = open_studio.main()
    assert exit_code == 0
    wb_open.assert_called_once()
    url_arg = wb_open.call_args.args[0]
    assert url_arg.startswith("http://")


def test_main_skips_browser_when_disabled(open_studio):
    with (
        patch.object(open_studio, "is_enabled", return_value=False),
        patch.object(open_studio.webbrowser, "open") as wb_open,
    ):
        exit_code = open_studio.main()
    assert exit_code == 0
    wb_open.assert_not_called()


def test_main_exits_cleanly_when_studio_never_comes_up(open_studio):
    """`make dev` must never be broken by a flaky browser opener."""
    with (
        patch.object(open_studio, "is_enabled", return_value=True),
        patch.object(open_studio, "wait_for_studio", return_value=False),
        patch.object(open_studio.webbrowser, "open") as wb_open,
    ):
        exit_code = open_studio.main()
    assert exit_code == 0
    wb_open.assert_not_called()


def test_main_swallows_webbrowser_error(open_studio):
    """If webbrowser.open raises, we log and continue — never error out."""
    import webbrowser as wb

    with (
        patch.object(open_studio, "is_enabled", return_value=True),
        patch.object(open_studio, "wait_for_studio", return_value=True),
        patch.object(open_studio.webbrowser, "open", side_effect=wb.Error("no browser")),
    ):
        exit_code = open_studio.main()
    assert exit_code == 0
