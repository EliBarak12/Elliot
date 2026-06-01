"""Token estimation: real tokenizer when available, chars/4 fallback."""

from __future__ import annotations

import json

import pytest

from elliot_connector_runtime import session_tracker
from elliot_connector_runtime.session_tracker import _estimate_tokens


def test_fallback_is_chars_over_four(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the no-tokenizer path and assert the documented heuristic.
    monkeypatch.setattr(session_tracker, "_encoder", lambda: None)
    data = [{"id": i, "name": "row"} for i in range(20)]
    expected = max(1, len(json.dumps(data, default=str)) // 4)
    assert _estimate_tokens(data) == expected


def test_estimate_is_positive_and_monotonic() -> None:
    small = _estimate_tokens([{"id": 1}])
    large = _estimate_tokens([{"id": i, "blob": "x" * 50} for i in range(100)])
    assert small >= 1
    assert large > small


def test_unserializable_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom:
        def __repr__(self) -> str:  # json.dumps(default=str) calls str() -> repr
            raise RuntimeError("nope")

    # default=str will call str(Boom()) -> repr -> raises, so json.dumps raises.
    assert _estimate_tokens(Boom()) == 0


def test_real_tokenizer_used_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    # If tiktoken loads, the count should match the encoder length exactly.
    enc = session_tracker._encoder()
    if enc is None:
        pytest.skip("tiktoken/vocab not available in this environment")
    data = [{"id": i} for i in range(10)]
    text = json.dumps(data, default=str)
    assert _estimate_tokens(data) == max(1, len(enc.encode(text)))
