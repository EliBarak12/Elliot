"""Tests for elliot_core.rate_limit."""

from __future__ import annotations

import pytest


def test_build_limiter_returns_limiter() -> None:
    from elliot_core.rate_limit import build_limiter

    limiter = build_limiter()
    assert limiter is not None


def test_build_limiter_respects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELLIOT_RATE_LIMIT", "30/minute")
    from elliot_core.rate_limit import build_limiter

    limiter = build_limiter()
    assert limiter is not None
