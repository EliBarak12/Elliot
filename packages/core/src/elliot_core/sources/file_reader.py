from __future__ import annotations

import csv
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


def read_file(config: SourceConfig) -> FetchResult:
    raw_path = config.path or ""
    if not raw_path:
        raise ElliotError("FILE_NOT_FOUND", "File path is empty")

    # Audit finding H3: previously `Path(config.path)` was opened verbatim,
    # so a writeable connector could read arbitrary host files. Resolve and
    # assert containment under one of the allowed roots (ELLIOT_FILE_ROOT
    # plus the framework-managed .elliot/sources/). Operators who need
    # absolute access can set ELLIOT_FILE_READER_ALLOW_ABSOLUTE=1.
    if _file_root_unrestricted():
        path: Path = Path(raw_path).resolve()
    else:
        roots = _allowed_roots()
        last_err: PathEscape | None = None
        resolved: Path | None = None
        for root in roots:
            try:
                resolved = ensure_under(root, raw_path)
                break
            except PathEscape as exc:
                last_err = exc
        if resolved is None:
            # Surface the actual allowed roots in the message itself. The MCP
            # transport drops `detail`, so without this the agent only sees
            # "outside the allowed roots" and has to probe with elliot_upload_file
            # just to discover where files belong.
            roots_str = ", ".join(str(r) for r in roots)
            attempted = last_err.candidate if last_err else raw_path
            raise ElliotError(
                "FILE_NOT_ALLOWED",
                f"File path {attempted!r} is outside the allowed roots. "
                f"Allowed roots: {roots_str}. "
                "Prefer elliot_upload_file (stages the file under the managed "
                "sources directory automatically); or copy the file under one "
                "of the allowed roots; or set ELLIOT_FILE_ROOT / "
                "ELLIOT_FILE_READER_ALLOW_ABSOLUTE=1 for trusted absolute paths.",
                detail={
                    "path": attempted,
                    "allowed_roots": [str(r) for r in roots],
                },
            ) from last_err
        path = resolved

    if not path.exists():
        raise ElliotError("FILE_NOT_FOUND", f"File not found: {config.path}")

    warnings: list[str] = []
    size = path.stat().st_size
    if size > _SIZE_WARN_BYTES:
        warnings.append(f"Large file ({size // 1_048_576} MB) — processing may be slow")

    fmt = config.format or _detect_format(path)
    try:
        rows = _read(path, fmt, config)
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


def _detect_format(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in ("jsonl", "ndjson"):
        return "jsonl"
    if suffix == "csv":
        return "csv"
    return "json"


def _read(path: Path, fmt: str, config: SourceConfig) -> list[dict[str, Any]]:
    if fmt == "csv":
        with path.open(encoding=config.encoding, newline="") as f:
            return [dict(row) for row in csv.DictReader(f, delimiter=config.delimiter)]

    if fmt == "jsonl":
        rows: list[dict[str, Any]] = []
        with path.open(encoding=config.encoding) as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    rows.append(json.loads(stripped))
        return rows

    # JSON
    data = json.loads(path.read_text(encoding=config.encoding))
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
