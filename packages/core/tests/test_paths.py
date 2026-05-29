"""Tests for elliot_core.paths containment guards."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from elliot_core.paths import PathEscape, ensure_under, safe_join

# ── safe_join ─────────────────────────────────────────────────────────────


def test_safe_join_normal(tmp_path: Path):
    out = safe_join(tmp_path, "child.json")
    assert out == (tmp_path / "child.json").resolve()


def test_safe_join_subdir(tmp_path: Path):
    out = safe_join(tmp_path, "sub/child.json")
    assert out == (tmp_path / "sub" / "child.json").resolve()


def test_safe_join_rejects_dotdot(tmp_path: Path):
    with pytest.raises(PathEscape, match="escapes"):
        safe_join(tmp_path, "../escape.json")


def test_safe_join_rejects_absolute(tmp_path: Path):
    # Use an OS-correct absolute path: on Windows '/etc/passwd' is relative
    # (no drive letter), so pick C:\etc\passwd there. Either way the join
    # must be rejected as absolute, not as a generic escape.
    abs_outside = "C:\\etc\\passwd" if sys.platform == "win32" else "/etc/passwd"
    with pytest.raises(PathEscape, match="absolute"):
        safe_join(tmp_path, abs_outside)


def test_safe_join_rejects_double_dotdot(tmp_path: Path):
    with pytest.raises(PathEscape, match="escapes"):
        safe_join(tmp_path, "child/../../escape")


def test_safe_join_rejects_empty(tmp_path: Path):
    with pytest.raises(PathEscape, match="empty"):
        safe_join(tmp_path, "")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="symlink creation requires SeCreateSymbolicLinkPrivilege on Windows",
)
def test_safe_join_rejects_symlink_escape(tmp_path: Path):
    # Build a symlink inside tmp_path that points to /tmp's sibling.
    outside = tmp_path.parent / "outside.json"
    outside.write_text("data")
    link = tmp_path / "link.json"
    link.symlink_to(outside)
    with pytest.raises(PathEscape, match="escapes"):
        safe_join(tmp_path, "link.json")


# ── ensure_under ──────────────────────────────────────────────────────────


def test_ensure_under_accepts_inside(tmp_path: Path):
    target = tmp_path / "data" / "file.json"
    out = ensure_under(tmp_path, target)
    assert out == target.resolve()


def test_ensure_under_rejects_outside(tmp_path: Path):
    target = tmp_path.parent / "elsewhere.json"
    with pytest.raises(PathEscape, match="not under"):
        ensure_under(tmp_path, target)


def test_ensure_under_rejects_empty(tmp_path: Path):
    with pytest.raises(PathEscape):
        ensure_under(tmp_path, "")
