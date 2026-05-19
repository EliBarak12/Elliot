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


def test_load_table_with_zero_columns_creates_placeholder(engine: SQLiteEngine):
    """Regression: empty nested JSON arrays (e.g. `"teaserBlocks": []`)
    produced FlattenedTables with zero columns, which previously emitted
    `CREATE TABLE "..." ()` and failed with `near ")": syntax error`."""
    from elliot_core.types.sqlite import FlattenedTable

    engine.load_table(FlattenedTable(name="empty_child", columns=[], rows=[]))
    assert "empty_child" in engine.get_table_names()
    schema = engine.get_table_schema("empty_child")
    assert [c["name"] for c in schema] == ["_empty"]


def test_load_result_handles_nested_empty_arrays(engine: SQLiteEngine):
    """Regression: a JSON payload with nested empty arrays (the getInsights
    shape: `facts.*.cols`, `teaserBlocks`, `actions`) used to fail with
    `[INTERNAL_ERROR] near ")": syntax error`. The whole tree must load."""
    data = [
        {
            "ok": True,
            "insights": [
                {
                    "id": "x",
                    "teaserBlocks": [],
                    "actions": [],
                    "facts": {
                        "confirmedTransaction": {
                            "type": "PTransaction",
                            "cols": [],
                            "rows": [],
                        }
                    },
                }
            ],
        }
    ]
    result = flatten(data, "get_insights_raw")
    engine.load_result(result)
    names = engine.get_table_names()
    assert "get_insights_raw" in names
    assert "get_insights_raw_insights" in names
    assert any("teaserblocks" in n for n in names)
    assert any("actions" in n for n in names)
    assert any("cols" in n for n in names)
    assert any("rows" in n for n in names)


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


# ── Authorizer: deny ATTACH / DETACH / triggers / unknown pragmas ───────────


def test_authorizer_blocks_attach(engine: SQLiteEngine):
    """Even a bare ATTACH issued directly on the connection must be denied —
    if validate_tool_sql is ever bypassed (mocked, model_construct, …) the
    authorizer is the last line of defense."""
    import sqlite3

    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        engine._conn.execute("ATTACH DATABASE ':memory:' AS evil")


def test_authorizer_blocks_detach(engine: SQLiteEngine):
    import sqlite3

    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        engine._conn.execute("DETACH DATABASE evil")


def test_authorizer_blocks_create_trigger(engine: SQLiteEngine):
    """CREATE TRIGGER lets a connector smuggle writes / side effects past a
    READ-only contract — explicitly denied."""
    import sqlite3

    engine.load_result(flatten([{"id": 1}], "t"))
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        engine._conn.execute('CREATE TRIGGER trg AFTER INSERT ON "t" BEGIN SELECT 1; END')


def test_authorizer_blocks_unknown_pragma(engine: SQLiteEngine):
    import sqlite3

    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        engine._conn.execute("PRAGMA writable_schema = ON")


def test_authorizer_allows_engine_pragmas(engine: SQLiteEngine):
    """The allowlist must keep the engine's own bootstrap + introspection
    pragmas working (foreign_keys, table_info)."""
    engine.load_result(flatten([{"id": 1}], "things"))
    # table_info is invoked by get_table_schema(); foreign_keys was set in
    # __init__ before this test ran without raising.
    schema = engine.get_table_schema("things")
    assert any(c["name"] == "id" for c in schema)
