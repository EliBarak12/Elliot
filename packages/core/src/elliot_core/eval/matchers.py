"""Deterministic value matchers for eval scoring.

No LLM, no I/O — these are pure functions so eval scoring stays reproducible
and unit-testable. They back the rich ``expect`` assertions in ``.eval.yaml``
suites (field-level assertions, ``all_rows_match``) and give an answer-style
eval a way to score a scalar response without the brittleness of ``==``.

The brittleness this fixes: an agent that answers ``$11,614.72`` to a question
whose ground truth is ``11614.72`` is *correct*, but a raw string compare marks
it wrong. ``numeric`` / ``normalized`` matching strips the currency symbol and
thousands separators and compares the underlying value.

Modes
-----
- ``exact``      — strict equality (the historical behaviour).
- ``numeric``    — parse both sides to a number and compare. Default tolerance:
  round both to the number of decimal places written in the *expected* literal
  (so ``87.2475`` matches an expected ``87.25``). ``abs_tol`` / ``rel_tol``
  override the default when given.
- ``scientific`` — compare in scientific form to the significant figures of the
  expected literal (so ``3.614e-19`` matches an expected ``3.61e-19``).
- ``normalized`` — numeric compare when both parse as numbers, else a
  case/whitespace-insensitive string compare.
- ``regex``      — the actual value must fully match the expected pattern.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import structlog

log = structlog.get_logger(__name__)

MatchMode = Literal["exact", "numeric", "scientific", "normalized", "regex"]

# Currency symbols, thousands separators, percent signs and surrounding space —
# stripped before a numeric parse so "$11,614.72" and "11614.72" compare equal.
_NUMERIC_NOISE_RE = re.compile(r"[,$%\s]")
_WS_RE = re.compile(r"\s+")


def _to_decimal(value: Any) -> Decimal | None:
    """Parse a scalar to ``Decimal`` (handling ``"$1,234.50"`` and ``"3.6e-19"``).

    Returns ``None`` when the value is not a number — including ``bool``, which
    Python treats as an ``int`` but is never a meaningful numeric answer.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if isinstance(value, str):
        cleaned = _NUMERIC_NOISE_RE.sub("", value.strip())
        if not cleaned:
            return None
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None
    return None


def _decimal_places(literal: Any) -> int:
    """Count the decimal places written in ``literal`` (fixed-point form only)."""
    s = _NUMERIC_NOISE_RE.sub("", str(literal).strip())
    if "e" in s.lower():
        return 0
    if "." in s:
        return len(s.split(".", 1)[1])
    return 0


def _sig_figs(literal: Any) -> int:
    """Count the significant figures in ``literal`` (at least 1)."""
    s = _NUMERIC_NOISE_RE.sub("", str(literal).strip()).lower()
    mantissa = s.split("e", 1)[0].lstrip("+-")
    digits = mantissa.replace(".", "")
    # Leading zeros are never significant; a value like 0.00350 keeps the
    # trailing zeros as significant, so only strip from the left.
    stripped = digits.lstrip("0")
    return len(stripped) or 1


def _round_sig(value: Decimal, sig: int) -> Decimal:
    """Round ``value`` to ``sig`` significant figures."""
    if value == 0:
        return Decimal(0)
    exponent = value.adjusted()  # power of ten of the most-significant digit
    quantum = Decimal(1).scaleb(exponent - (sig - 1))
    return value.quantize(quantum)


def match_numeric(
    actual: Any,
    expected: Any,
    *,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
) -> bool:
    """Compare two values numerically.

    Default (no tolerance given): round both to the decimal places of the
    ``expected`` literal and compare. ``abs_tol`` wins over ``rel_tol`` when both
    are supplied.
    """
    a = _to_decimal(actual)
    e = _to_decimal(expected)
    if a is None or e is None:
        return False
    if abs_tol is not None:
        return abs(a - e) <= Decimal(str(abs_tol))
    if rel_tol is not None:
        denom = abs(e) if e != 0 else Decimal(1)
        return abs(a - e) / denom <= Decimal(str(rel_tol))
    quantum = Decimal(1).scaleb(-_decimal_places(expected))
    return a.quantize(quantum) == e.quantize(quantum)


def match_scientific(actual: Any, expected: Any, *, sig_figs: int | None = None) -> bool:
    """Compare two values to the significant figures of the ``expected`` literal."""
    a = _to_decimal(actual)
    e = _to_decimal(expected)
    if a is None or e is None:
        return False
    if a == 0 or e == 0:
        return a == e
    sig = sig_figs if sig_figs is not None else _sig_figs(expected)
    return _round_sig(a, sig) == _round_sig(e, sig)


def _norm_str(value: Any) -> str:
    return _WS_RE.sub(" ", str(value).strip().lower())


def match_normalized(actual: Any, expected: Any) -> bool:
    """Numeric compare when both parse as numbers, else case/space-insensitive."""
    a = _to_decimal(actual)
    e = _to_decimal(expected)
    if a is not None and e is not None:
        return a == e
    return _norm_str(actual) == _norm_str(expected)


def match_regex(actual: Any, pattern: Any) -> bool:
    """Return whether ``actual`` fully matches the regex ``pattern``."""
    try:
        return re.fullmatch(str(pattern), str(actual)) is not None
    except re.error as exc:
        log.warning("eval.matcher.bad_regex", pattern=str(pattern), error=str(exc))
        return False


def match_value(
    actual: Any,
    expected: Any,
    mode: MatchMode = "exact",
    *,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
    sig_figs: int | None = None,
) -> bool:
    """Dispatch to the matcher for ``mode``. Raises on an unknown mode."""
    if mode == "exact":
        return actual == expected
    if mode == "numeric":
        return match_numeric(actual, expected, abs_tol=abs_tol, rel_tol=rel_tol)
    if mode == "scientific":
        return match_scientific(actual, expected, sig_figs=sig_figs)
    if mode == "normalized":
        return match_normalized(actual, expected)
    if mode == "regex":
        return match_regex(actual, expected)
    raise ValueError(f"Unknown match mode: {mode!r}")
