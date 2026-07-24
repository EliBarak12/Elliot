"""Canonical token estimate for a tool result.

Token cost is Elliot's signature metric — "results sized for context windows"
(principle 2). It must be counted ONE way across the platform: the runtime's
per-call trace, the observation store, the eval token budgets, and the
context-footprint grade. When each surface rolled its own estimate (some
tiktoken, some ``len(text) // 4``), the same result reported different token
counts depending on where you looked, quietly undermining the one number the
product is built around. This module is that single definition; every surface
imports ``estimate_tokens`` from here.
"""

from __future__ import annotations

import contextlib
import functools
import json
from typing import Any


@functools.lru_cache(maxsize=1)
def _encoder() -> Any | None:
    """Return a tiktoken encoder if available, else ``None``.

    A token count is only as good as the tokenizer. When ``tiktoken`` is
    installed we use ``cl100k_base`` (a solid cross-model proxy) for a real
    count instead of a heuristic. When it isn't installed — or its BPE vocab
    can't be loaded (e.g. offline) — we fall back to chars/4. Cached so the
    vocab loads at most once per process.
    """
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def estimate_tokens(data: Any) -> int:
    """Estimate the token cost of a tool result.

    Serializes ``data`` to JSON and counts with a real tokenizer (tiktoken
    ``cl100k_base``) when available, otherwise the chars/4 heuristic. Both paths
    are model-approximate — the figure powers the token-efficiency dashboard,
    the eval token gates, and the footprint grade, not billing — but they are
    now the SAME figure everywhere, which is the point."""
    try:
        text = json.dumps(data, default=str)
    except Exception:
        return 0
    enc = _encoder()
    if enc is not None:
        with contextlib.suppress(Exception):
            return max(1, len(enc.encode(text)))
    return max(1, len(text) // 4)
