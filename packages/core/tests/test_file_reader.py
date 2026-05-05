from pathlib import Path

import pytest

from elliot_core.errors import ElliotError
from elliot_core.sources.file_reader import read_file
from elliot_core.types.source import SourceConfig

FIXTURES = Path(__file__).parent / "fixtures"


def _cfg(path: str, fmt: str | None = None) -> SourceConfig:
    return SourceConfig(
        id="test",
        name="test",
        type="file",
        path=str(path),
        format=fmt,
    )


def test_csv_reads_all_rows():
    result = read_file(_cfg(FIXTURES / "customers.csv", "csv"))
    assert len(result.rows) == 5
    assert result.rows[0]["name"] == "Alice Smith"


def test_json_envelope_unwrap():
    result = read_file(_cfg(FIXTURES / "orders.json", "json"))
    assert len(result.rows) == 3
    assert result.rows[0]["id"] == "ord-001"


def test_jsonl_line_by_line():
    result = read_file(_cfg(FIXTURES / "events.jsonl", "jsonl"))
    assert len(result.rows) == 5
    assert result.rows[0]["type"] == "page_view"


def test_missing_file_raises():
    with pytest.raises(ElliotError) as exc_info:
        read_file(_cfg("/does/not/exist.csv"))
    assert exc_info.value.code == "FILE_NOT_FOUND"


def test_invalid_json_raises(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    with pytest.raises(ElliotError) as exc_info:
        read_file(_cfg(str(bad), "json"))
    assert exc_info.value.code == "FILE_PARSE_ERROR"


def test_empty_file_warning(tmp_path: Path):
    empty = tmp_path / "empty.csv"
    empty.write_text("id,name\n")
    result = read_file(_cfg(str(empty), "csv"))
    assert result.rows == []
    assert any("empty" in w.lower() for w in result.warnings)
