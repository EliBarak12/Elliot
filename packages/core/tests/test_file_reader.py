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


def test_csv_large_field_does_not_raise(tmp_path: Path):
    """Regression: business CSVs routinely embed JSON-shaped fields > 128KB.
    The old default raised `FILE_PARSE_ERROR: field larger than field limit`."""
    csv_path = tmp_path / "wide.csv"
    big_blob = "x" * 200_000
    csv_path.write_text(f"id,payload\n1,{big_blob}\n", encoding="utf-8")
    result = read_file(_cfg(str(csv_path), "csv"))
    assert len(result.rows) == 1
    assert len(result.rows[0]["payload"]) == 200_000


def test_json_unwrap_arbitrary_key(tmp_path: Path):
    """Regression: a 4.7 MB connector source file with records nested
    under an arbitrary key (e.g. `insights`) used to be returned as a
    single 1-row document. The unwrapper should find the records list
    even when its key isn't one of the well-known envelope names."""
    import json as _json

    path = tmp_path / "insights.json"
    path.write_text(
        _json.dumps(
            {
                "version": "1.0",
                "insights": [
                    {"id": "a", "kind": "trend"},
                    {"id": "b", "kind": "anomaly"},
                    {"id": "c", "kind": "summary"},
                ],
                "meta": {"generated_at": "2026-01-01"},
            }
        )
    )

    result = read_file(_cfg(str(path), "json"))
    assert len(result.rows) == 3
    assert {r["id"] for r in result.rows} == {"a", "b", "c"}


def test_json_unwrap_prefers_largest_list_of_dicts(tmp_path: Path):
    """When a document has multiple list values, the largest list of
    dicts wins — sidecars like `errors: [...]` shouldn't shadow the
    real records list."""
    import json as _json

    path = tmp_path / "doc.json"
    path.write_text(
        _json.dumps(
            {
                "errors": [{"code": "X"}],
                "things": [{"id": i} for i in range(10)],
            }
        )
    )

    result = read_file(_cfg(str(path), "json"))
    assert len(result.rows) == 10


def test_json_unwrap_well_known_key_beats_largest(tmp_path: Path):
    """The well-known envelope keys (data/items/...) take priority over
    the largest-list heuristic, preserving existing behavior."""
    import json as _json

    path = tmp_path / "doc.json"
    path.write_text(
        _json.dumps(
            {
                "data": [{"id": 1}],
                # A larger sibling list — but `data` still wins.
                "_unused": [{"x": i} for i in range(100)],
            }
        )
    )

    result = read_file(_cfg(str(path), "json"))
    assert len(result.rows) == 1
    assert result.rows[0]["id"] == 1


def test_json_unwrap_ignores_lists_of_scalars(tmp_path: Path):
    """A list of primitives (tags, labels) shouldn't be mistaken for the
    records list — fall through to single-row wrap of the dict."""
    import json as _json

    path = tmp_path / "doc.json"
    path.write_text(
        _json.dumps(
            {
                "name": "config",
                "tags": ["alpha", "beta", "gamma"],
            }
        )
    )

    result = read_file(_cfg(str(path), "json"))
    assert len(result.rows) == 1
    assert result.rows[0]["name"] == "config"


def test_file_not_allowed_message_names_allowed_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: the message used to say only "outside the allowed roots",
    leaving agents to probe with elliot_upload_file to discover where files
    belong. The actual roots must appear in the visible message."""
    monkeypatch.delenv("ELLIOT_FILE_READER_ALLOW_ABSOLUTE", raising=False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("ELLIOT_FILE_ROOT", str(workspace))

    outside = tmp_path / "outside.json"
    outside.write_text("[]")

    with pytest.raises(ElliotError) as exc_info:
        read_file(_cfg(str(outside), "json"))

    err = exc_info.value
    assert err.code == "FILE_NOT_ALLOWED"
    assert str(workspace) in err.message
    assert "elliot_upload_file" in err.message
    assert err.detail is not None
    assert str(workspace) in err.detail["allowed_roots"]
