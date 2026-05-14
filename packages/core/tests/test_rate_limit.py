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
    # Audit Medium 10: previously only `limiter is not None` was asserted,
    # so a regression that built the wrong rate would silently pass.
    # Walk into the LimitGroup -> Limit objects and assert the resolved
    # rate matches what the env var configured.
    group = limiter._default_limits[0]
    items = list(group)
    assert items, "LimitGroup must materialise at least one Limit"
    descriptions = [str(item.limit) for item in items]
    assert any("30" in d for d in descriptions), (
        f"Expected ELLIOT_RATE_LIMIT=30/minute to round-trip into the limiter; got {descriptions!r}"
    )


def test_build_limiter_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the env var is unset, the limiter must fall back to a sane default."""
    monkeypatch.delenv("ELLIOT_RATE_LIMIT", raising=False)
    from elliot_core.rate_limit import build_limiter

    limiter = build_limiter()
    assert limiter._default_limits, "default limit must be set when env var is unset"
