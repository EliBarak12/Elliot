import pytest

from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.sqlite.flattener import flatten


@pytest.fixture
def engine():
    e = SQLiteEngine()
    yield e
    e.close()


def test_load_and_query(engine: SQLiteEngine):
    result = flatten([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}], "users")
    engine.load_result(result)
    rows = engine.query('SELECT * FROM "users"')
    assert len(rows) == 2
    assert {r["name"] for r in rows} == {"Alice", "Bob"}


def test_get_table_names(engine: SQLiteEngine):
    engine.load_result(flatten([{"x": 1}], "items"))
    assert "items" in engine.get_table_names()


def test_get_table_schema(engine: SQLiteEngine):
    engine.load_result(flatten([{"price": 9.99}], "products"))
    schema = engine.get_table_schema("products")
    col_names = [col["name"] for col in schema]
    assert "price" in col_names


def test_get_table_stats(engine: SQLiteEngine):
    engine.load_result(flatten([{"v": 1}, {"v": 2}, {"v": 3}], "t"))
    stats = engine.get_table_stats("t")
    assert stats["row_count"] == 3


def test_profile_column(engine: SQLiteEngine):
    result = flatten([{"val": 10}, {"val": 20}, {"val": 10}], "nums")
    engine.load_result(result)
    profile = engine.profile_column("nums", "val")
    assert profile["min_val"] == 10
    assert profile["max_val"] == 20
    assert profile["distinct_count"] == 2
    assert 10 in profile["top_values"]


def test_related_table_loaded(engine: SQLiteEngine):
    data = [{"id": 1, "tags": [{"name": "python"}, {"name": "api"}]}]
    result = flatten(data, "projects")
    engine.load_result(result)
    child_names = engine.get_table_names()
    assert any("tags" in n for n in child_names)


def test_query_with_params(engine: SQLiteEngine):
    engine.load_result(flatten([{"name": "Alice"}, {"name": "Bob"}], "users"))
    rows = engine.query('SELECT * FROM "users" WHERE "name" = :name', {"name": "Alice"})
    assert len(rows) == 1
    assert rows[0]["name"] == "Alice"


def test_bad_sql_raises_elliot_error(engine: SQLiteEngine):
    from elliot_core.errors import ElliotError

    with pytest.raises(ElliotError) as exc_info:
        engine.query("THIS IS NOT VALID SQL !!!")
    assert exc_info.value.code == "INVALID_SQL"


def test_ingest_empty_rows_creates_placeholder_table(engine: SQLiteEngine):
    engine.ingest("empty_tbl", [])
    tables = engine.get_table_names()
    assert "empty_tbl" in tables


def test_ingest_handles_list_values_without_raising(engine: SQLiteEngine):
    """Regression: real-world JSON rows contain lists/dicts; ingest used to
    fail with 'type list is not supported' from sqlite parameter binding."""
    engine.ingest(
        "facts",
        [
            {"id": 1, "tags": ["a", "b"], "meta": {"k": "v"}},
            {"id": 2, "tags": [1, 2, 3], "meta": None},
        ],
    )
    rows = engine.query('SELECT * FROM "facts" ORDER BY id')
    assert len(rows) == 2
    # Lists/dicts get JSON-stringified so they round-trip as text.
    assert '"a"' in rows[0]["tags"] and '"b"' in rows[0]["tags"]
    assert rows[1]["meta"] is None


def test_ingest_rolls_back_partial_table_on_failure(engine: SQLiteEngine):
    """Regression: discovery failures used to leave partial tables visible
    via subsequent get_schema calls."""
    engine.ingest("good_table", [{"x": 1}])
    assert "good_table" in engine.get_table_names()

    # A column name with an embedded quote produces invalid CREATE TABLE
    # SQL — the rollback path must drop the half-built table.
    bad_rows = [{'name"; DROP': "evil"}]
    with pytest.raises(Exception):  # noqa: B017
        engine.ingest("bad_table", bad_rows)
    assert "bad_table" not in engine.get_table_names()
    assert "good_table" in engine.get_table_names()


def test_load_result_rolls_back_when_child_table_fails(
    engine: SQLiteEngine, monkeypatch: pytest.MonkeyPatch
):
    """If a related child table fails to load, the primary table must NOT
    remain visible — load_result is atomic."""
    result = flatten(
        [{"id": 1, "tags": [{"name": "python"}, {"name": "api"}]}],
        "projects",
    )

    real_load_table = engine.load_table
    call_count = {"n": 0}

    def flaky_load_table(table, *, commit: bool = True) -> None:  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated child-table failure")
        real_load_table(table, commit=commit)

    monkeypatch.setattr(engine, "load_table", flaky_load_table)

    with pytest.raises(RuntimeError, match="simulated child-table failure"):
        engine.load_result(result)

    tables = engine.get_table_names()
    assert "projects" not in tables
    assert not any("tags" in t for t in tables)
