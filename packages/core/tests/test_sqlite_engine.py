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
    # A numeric range is not an enum candidate — only text categories are.
    assert profile["enum_candidate"] is False


def test_profile_column_flags_text_enum_candidate(engine: SQLiteEngine):
    rows = [{"status": s} for s in ["open", "closed", "open", "pending", "open", "closed"]]
    engine.load_result(flatten(rows, "orders"))
    profile = engine.profile_column("orders", "status")
    assert profile["enum_candidate"] is True
    # The exact allowed values ride along so the agent can declare the enum.
    assert sorted(profile["enum_values"]) == ["closed", "open", "pending"]


def test_profile_column_unique_text_is_not_an_enum(engine: SQLiteEngine):
    # Every value distinct (a near-key like an email) — no repetition, so it is
    # not a category and must not be flagged.
    rows = [{"email": f"user{i}@x.com"} for i in range(8)]
    engine.load_result(flatten(rows, "people"))
    profile = engine.profile_column("people", "email")
    assert profile["enum_candidate"] is False
    assert "enum_values" not in profile


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


def test_profile_column_offers_the_values_inside_lists(engine: SQLiteEngine):
    """A column of arrays arrives as JSON text. Its text values are not the
    enum: the values inside are, filtered by membership."""
    rows = [
        {"name": "Pasta", "meal_type": ["Dinner"]},
        {"name": "Salad", "meal_type": ["Lunch", "Dinner"]},
        {"name": "Eggs", "meal_type": ["Breakfast"]},
        {"name": "Soup", "meal_type": ["Lunch", "Dinner"]},
        {"name": "Toast", "meal_type": ["Breakfast"]},
        {"name": "Stew", "meal_type": ["Dinner"]},
    ]
    engine.load_result(flatten(rows, "recipes"))
    profile = engine.profile_column("recipes", "meal_type")
    assert profile["enum_candidate"] is False
    assert "enum_values" not in profile
    assert profile["list_column"] is True
    assert profile["list_values"] == ["Breakfast", "Dinner", "Lunch"]

    # The filter it offers works: Dinner is in four recipes' lists.
    sql = f"SELECT name FROM recipes WHERE {profile['list_filter']} ORDER BY name"
    names = [r["name"] for r in engine.query(sql, {"meal_type": "Dinner"})]
    assert names == ["Pasta", "Salad", "Soup", "Stew"]
    assert len(engine.query(sql, {"meal_type": None})) == 6
    # And grouping by it counts each value once per recipe that has it.
    grouped = {r["meal_type"]: r["COUNT(*)"] for r in engine.query(profile["list_group_by"], {})}
    assert grouped == {"Breakfast": 2, "Dinner": 4, "Lunch": 2}


def test_profile_column_lists_of_objects_are_not_list_columns(engine: SQLiteEngine):
    rows = [{"tags": '[{"a": 1}]'} for _ in range(4)] + [{"tags": "[]"}]
    engine.load_result(flatten(rows, "things"))
    profile = engine.profile_column("things", "tags")
    assert "list_column" not in profile


def test_matches_words_finds_what_a_phrase_search_misses(engine: SQLiteEngine):
    """An agent types words. Each one is matched on its own across the columns,
    a plural finds its singular, and no query is no filter."""
    rows = [
        {"title": "iPhone 12 Silicone Case", "tags": ["mobile", "accessory"], "description": None},
        {
            "title": "Calvin Klein CK One",
            "tags": ["fragrances", "perfume"],
            "description": "A unisex scent",
        },
        {"title": "Kitchen Sieve", "tags": ["kitchen"], "description": "Steel sieve"},
    ]
    engine.load_result(flatten(rows, "products"))
    sql = "SELECT title FROM products WHERE matches_words(:q, title, description, tags) ORDER BY title"

    def find(q):  # type: ignore[no-untyped-def]
        return [r["title"] for r in engine.query(sql, {"q": q})]

    assert find("phone cases") == ["iPhone 12 Silicone Case"]  # two words, a plural
    assert find("PERFUMES") == ["Calvin Klein CK One"]  # in the tags, any case
    assert find("steel kitchen") == ["Kitchen Sieve"]  # words from two columns
    assert find("kitchen phone") == []  # every word must appear
    assert len(find(None)) == 3 and len(find("  ")) == 3  # optional by itself
