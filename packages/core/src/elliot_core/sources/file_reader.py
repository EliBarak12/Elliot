from __future__ import annotations

import base64
import binascii
import csv
import io
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from elliot_core.errors import ElliotError
from elliot_core.paths import PathEscape, ensure_under
from elliot_core.types.source import FetchResult, SourceConfig

_SIZE_WARN_BYTES = 100 * 1024 * 1024  # 100 MB
_DEFAULT_MAX_FILE_BYTES = 256 * 1024 * 1024  # 256 MB hard cap


def _max_file_bytes() -> int:
    """Hard upper bound on a file source's size (env ELLIOT_MAX_FILE_BYTES).

    The JSON path loads the whole file into memory, so without a ceiling a
    very large (or maliciously crafted) file is a DoS vector.
    """
    raw = os.environ.get("ELLIOT_MAX_FILE_BYTES", "")
    try:
        return max(1024, int(raw)) if raw else _DEFAULT_MAX_FILE_BYTES
    except ValueError:
        return _DEFAULT_MAX_FILE_BYTES


def _allowed_roots() -> list[Path]:
    """Return every directory tree under which file: sources may live.

    The list is the union of:

    - ``ELLIOT_FILE_ROOT`` (defaults to the current working directory) — the
      operator-controlled root for connector data files.
    - The session's framework-managed sources directory (``.elliot/sources/``
      under cwd, or the explicit ``ELLIOT_MANAGED_SOURCES_DIR`` override).
      This is where ``elliot_upload_file`` stages agent-uploaded content; it
      is always allowed regardless of how ``ELLIOT_FILE_ROOT`` is set so the
      upload→discover flow works without env tuning.

    Setting ``ELLIOT_FILE_READER_ALLOW_ABSOLUTE=1`` disables containment
    entirely — for trusted environments only.
    """
    roots = [Path(os.environ.get("ELLIOT_FILE_ROOT", os.getcwd())).resolve()]
    managed = Path(
        os.environ.get("ELLIOT_MANAGED_SOURCES_DIR")
        or os.path.join(os.getcwd(), ".elliot", "sources")
    ).resolve()
    if managed not in roots:
        roots.append(managed)
    return roots


def _file_root_unrestricted() -> bool:
    return os.environ.get("ELLIOT_FILE_READER_ALLOW_ABSOLUTE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# Real business CSVs routinely embed JSON-shaped fields that blow past
# Python's 131072-byte default. Raise to the platform's int max so a single
# oversized cell doesn't surface as `FILE_PARSE_ERROR: field larger than
# field limit`. Wrapped because some platforms cap below sys.maxsize.
def _raise_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 2


_raise_csv_field_limit()


def resolve_source_path(raw_path: str) -> Path:
    """Resolve a file source's ``path`` to a concrete, containment-checked Path.

    Audit finding H3: previously ``Path(config.path)`` was opened verbatim, so a
    writeable connector could read arbitrary host files. Resolve and assert
    containment under one of the allowed roots (``ELLIOT_FILE_ROOT`` plus the
    framework-managed ``.elliot/sources/``). Operators who need absolute access
    can set ``ELLIOT_FILE_READER_ALLOW_ABSOLUTE=1``. Raises ``ElliotError`` with
    code ``FILE_NOT_ALLOWED`` when the path escapes every allowed root.
    """
    if not raw_path:
        raise ElliotError("FILE_NOT_FOUND", "File path is empty")
    if _file_root_unrestricted():
        return Path(raw_path).resolve()
    roots = _allowed_roots()
    last_err: PathEscape | None = None
    for root in roots:
        try:
            return ensure_under(root, raw_path)
        except PathEscape as exc:
            last_err = exc
    # Surface the actual allowed roots in the message itself. The MCP transport
    # drops `detail`, so without this the agent only sees "outside the allowed
    # roots" and has to probe just to discover where files belong.
    roots_str = ", ".join(str(r) for r in roots)
    attempted = last_err.candidate if last_err else raw_path
    raise ElliotError(
        "FILE_NOT_ALLOWED",
        f"File path {attempted!r} is outside the allowed roots. "
        f"Allowed roots: {roots_str}. "
        "Prefer passing the file content inline to elliot_discover_source "
        "(config={'content': ..., 'format': ...}) or elliot_upload_file (stages "
        "the file under the managed sources directory automatically); or copy "
        "the file under one of the allowed roots; or set ELLIOT_FILE_ROOT / "
        "ELLIOT_FILE_READER_ALLOW_ABSOLUTE=1 for trusted absolute paths.",
        detail={"path": attempted, "allowed_roots": [str(r) for r in roots]},
    ) from last_err


def read_file(config: SourceConfig) -> FetchResult:
    # Inline content takes precedence over `path`: a self-contained file source
    # carries its bytes in the config itself, so it materializes without any
    # host filesystem access (the cloud builder and runtime have no shared disk).
    if config.content is not None:
        return _read_inline(config)

    path = resolve_source_path(config.path or "")

    if not path.exists():
        raise ElliotError("FILE_NOT_FOUND", f"File not found: {config.path}")

    warnings: list[str] = []
    size = path.stat().st_size
    max_bytes = _max_file_bytes()
    if size > max_bytes:
        raise ElliotError(
            "FILE_TOO_LARGE",
            f"File {config.path} is {size // 1_048_576} MB, exceeding the "
            f"{max_bytes // 1_048_576} MB limit. Raise ELLIOT_MAX_FILE_BYTES "
            "if this is expected.",
        )
    if size > _SIZE_WARN_BYTES:
        warnings.append(f"Large file ({size // 1_048_576} MB) — processing may be slow")

    fmt = config.format or _detect_format(path)
    # Read raw text with newline translation disabled so the csv module sees
    # embedded newlines in quoted fields exactly as written.
    with path.open(encoding=config.encoding, newline="") as f:
        text = f.read()
    try:
        rows = _parse(text, fmt, config)
    except ElliotError:
        raise
    except json.JSONDecodeError as exc:
        raise ElliotError("FILE_PARSE_ERROR", f"Invalid JSON in {config.path}: {exc}") from exc
    except Exception as exc:
        raise ElliotError("FILE_PARSE_ERROR", f"Failed to parse {config.path}: {exc}") from exc

    if not rows:
        warnings.append(f"File is empty: {config.path}")

    return FetchResult(
        rows=rows,
        fetched_at=datetime.now(UTC).isoformat(),
        warnings=warnings,
    )


def _read_inline(config: SourceConfig) -> FetchResult:
    """Materialize a file source from its inline ``content`` (no filesystem)."""
    raw = config.content or ""
    max_bytes = _max_file_bytes()
    warnings: list[str] = []

    if config.content_encoding == "base64":
        try:
            data = base64.b64decode(raw, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ElliotError(
                "FILE_PARSE_ERROR", "inline file content is not valid base64"
            ) from exc
        if len(data) > max_bytes:
            raise ElliotError(
                "FILE_TOO_LARGE",
                f"inline content is {len(data) // 1_048_576} MB, exceeding the "
                f"{max_bytes // 1_048_576} MB limit. Raise ELLIOT_MAX_FILE_BYTES "
                "if this is expected.",
            )
        try:
            text = data.decode(config.encoding)
        except UnicodeDecodeError as exc:
            raise ElliotError(
                "FILE_PARSE_ERROR",
                f"inline content is not valid {config.encoding} text after base64 decode",
            ) from exc
    else:
        # Text content: cap on the encoded byte size, not the character count.
        size = len(raw.encode(config.encoding, errors="replace"))
        if size > max_bytes:
            raise ElliotError(
                "FILE_TOO_LARGE",
                f"inline content is {size // 1_048_576} MB, exceeding the "
                f"{max_bytes // 1_048_576} MB limit. Raise ELLIOT_MAX_FILE_BYTES "
                "if this is expected.",
            )
        if size > _SIZE_WARN_BYTES:
            warnings.append(
                f"Large inline content ({size // 1_048_576} MB) — processing may be slow"
            )
        text = raw

    # No filename to sniff, so default to JSON when the author didn't say.
    fmt = config.format or "json"
    try:
        rows = _parse(text, fmt, config)
    except ElliotError:
        raise
    except json.JSONDecodeError as exc:
        raise ElliotError("FILE_PARSE_ERROR", f"Invalid JSON in inline content: {exc}") from exc
    except Exception as exc:
        raise ElliotError("FILE_PARSE_ERROR", f"Failed to parse inline content: {exc}") from exc

    if not rows:
        warnings.append("Inline file content is empty")

    return FetchResult(
        rows=rows,
        fetched_at=datetime.now(UTC).isoformat(),
        warnings=warnings,
    )


def _detect_format(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in ("jsonl", "ndjson"):
        return "jsonl"
    if suffix == "csv":
        return "csv"
    return "json"


def _parse(text: str, fmt: str, config: SourceConfig) -> list[dict[str, Any]]:
    """Parse raw file text into rows. Shared by the path and inline-content paths."""
    if fmt == "csv":
        buf = io.StringIO(text, newline="")
        return [dict(row) for row in csv.DictReader(buf, delimiter=config.delimiter)]

    if fmt == "jsonl":
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
        return rows

    # JSON
    data = json.loads(text)
    return _unwrap_json(data)


def _unwrap_json(data: Any) -> list[dict[str, Any]]:
    """Find the list-of-records inside an arbitrary JSON document.

    Priority:
      1. Top-level list — return as-is.
      2. Well-known envelope keys (data/items/results/records/rows) whose
         value is a list. These match REST conventions and stay stable
         regardless of document size.
      3. Any other top-level key whose value is a non-empty list of dicts.
         Picks the longest such list — bigger usually means "the records"
         vs. a sidecar like "errors" or "meta". This is what unblocks
         agent-built connectors against files like ``getInsights.json``
         which nest the records under an arbitrary key.
      4. Fallback: a single-dict document → wrap as ``[data]``. Other
         shapes (top-level scalar, list of scalars) → ``[]``.
    """
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("data", "items", "results", "records", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return value

        # Largest list-of-dicts wins. Avoid sidecar lists of scalars
        # (e.g. ["error1", "error2"]) by requiring dict elements.
        best: list[dict[str, Any]] | None = None
        for value in data.values():
            if (
                isinstance(value, list)
                and value
                and all(isinstance(item, dict) for item in value)
                and (best is None or len(value) > len(best))
            ):
                best = value
        if best is not None:
            return best

        return [data]

    return []
