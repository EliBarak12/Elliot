"""Tests for the canonical token estimate (the signature metric)."""

from __future__ import annotations

import json

from elliot_core.tokens import _encoder, estimate_tokens


def test_estimate_tokens_is_positive_for_content() -> None:
    assert estimate_tokens([{"id": 1, "name": "widget"}]) > 0
    # Empty-ish payloads still cost at least one token (the serialized braces).
    assert estimate_tokens([]) >= 1


def test_estimate_tokens_uses_the_real_tokenizer_when_available() -> None:
    # In the test env tiktoken is installed, so the estimate must equal a direct
    # cl100k_base encode of the serialized data — not the chars/4 heuristic.
    enc = _encoder()
    assert enc is not None, "tiktoken should be available in the engine env"
    data = [{"id": i, "status": "open", "note": "hello world " * 5} for i in range(4)]
    text = json.dumps(data, default=str)
    assert estimate_tokens(data) == len(enc.encode(text))


def test_estimate_tokens_handles_unserializable_gracefully() -> None:
    # default=str stringifies a non-JSON type (a set) rather than raising, so
    # the estimate is always best-effort and never blows up a call.
    assert estimate_tokens({"x": {1, 2, 3}}) >= 1
