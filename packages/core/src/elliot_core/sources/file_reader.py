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


def _file_root() -> Path:
    """Return the directory tree that file: sources are restricted to.

    Defaults to the current working directory (the project root in normal
    runs). Operators can override with ELLIOT_FILE_ROOT for deployments
    where connector data files live elsewhere. Setting
    ELLIOT_FILE_READER_ALLOW_ABSOLUTE=1 disables the containment check
    entirely — for trusted environments only.
    """
    return Path(os.environ.get("ELLIOT_FILE_ROOT", os.getcwd())).resolve()


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
    # assert containment under ELLIOT_FILE_ROOT (defaults to cwd). Operators
    # who need absolute access can set ELLIOT_FILE_READER_ALLOW_ABSOLUTE=1.
    if _file_root_unrestricted():
        path = Path(raw_path).resolve()
    else:
        try:
            path = ensure_under(_file_root(), raw_path)
        except PathEscape as exc:
            raise ElliotError(
                "FILE_NOT_ALLOWED",
                "File path is outside the allowed root. "
                "Set ELLIOT_FILE_ROOT or ELLIOT_FILE_READER_ALLOW_ABSOLUTE=1 for trusted paths.",
                detail={"path": exc.candidate},
            ) from exc

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
    if isinstance(data, list):
        return data
    for key in ("data", "items", "results", "records"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
    return [data] if isinstance(data, dict) else []
