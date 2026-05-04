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
