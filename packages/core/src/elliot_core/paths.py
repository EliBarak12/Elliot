"""Path containment helpers.

Use these instead of bare ``Path()`` whenever the candidate path is influenced
by an agent or a connector author. Defends against ``../`` traversal and
absolute-path escapes by resolving both ``root`` and ``candidate`` and
asserting ``candidate.resolve()`` is under ``root.resolve()``.

Audit findings C4 (save_draft arbitrary file write), C5 (elliot_start_runtime
subprocess + env), and H3 (file_reader path traversal).
"""

from __future__ import annotations

import os
from pathlib import Path

from elliot_core.errors import ElliotError


class PathEscape(ElliotError):  # noqa: N818 - kept as a noun for readability; subclass of ElliotError
    """Raised when a candidate path would resolve outside the allowed root."""

    def __init__(self, message: str, candidate: str | None = None) -> None:
        super().__init__("PATH_ESCAPE", message, detail={"candidate": candidate})
        self.candidate = candidate


def safe_join(root: str | os.PathLike[str], candidate: str | os.PathLike[str]) -> Path:
    """Join ``candidate`` onto ``root`` and assert the result stays under root.

    Both paths are ``.resolve()``-ed so symlinks pointing outside the root
    are also rejected. Returns the resolved candidate path on success.
    Raises :class:`PathEscape` on any attempt to escape.
    """
    if candidate is None:
        raise PathEscape("candidate path is empty", candidate=None)
    root_p = Path(root).resolve()
    # Reject absolute candidates outright — the join semantics in Path()
    # would silently discard the root if the candidate is absolute.
    cand_str = os.fspath(candidate)
    if not cand_str:
        raise PathEscape("candidate path is empty", candidate=cand_str)
    candidate_path = Path(cand_str)
    if candidate_path.is_absolute():
        raise PathEscape(
            "absolute paths are not allowed; provide a path relative to the root",
            candidate=cand_str,
        )
    resolved = (root_p / candidate_path).resolve()
    try:
        resolved.relative_to(root_p)
    except ValueError as exc:
        raise PathEscape(
            f"path escapes the allowed root '{root_p}'",
            candidate=cand_str,
        ) from exc
    return resolved


def ensure_under(root: str | os.PathLike[str], candidate: str | os.PathLike[str]) -> Path:
    """Assert ``candidate`` (absolute OR relative) resolves under ``root``.

    Unlike :func:`safe_join`, this accepts an already-absolute candidate and
    only checks containment. Use when the caller intentionally supplies an
    absolute path that must still live under a trusted root.
    """
    if candidate is None:
        raise PathEscape("candidate path is empty", candidate=None)
    cand_str = os.fspath(candidate)
    root_p = Path(root).resolve()
    cand_p = Path(cand_str).resolve()
    try:
        cand_p.relative_to(root_p)
    except ValueError as exc:
        raise PathEscape(
            f"path '{cand_str}' is not under allowed root '{root_p}'",
            candidate=cand_str,
        ) from exc
    return cand_p
