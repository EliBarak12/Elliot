from elliot_core.sqlite.flattener import MAX_ARRAY_ROWS, flatten


def test_primitive_fields():
    result = flatten([{"name": "Alice", "age": 30}], "users")
    row = result.primary_table.rows[0]
    assert row["name"] == "Alice"
    assert row["age"] == 30


def test_bool_becomes_int():
    result = flatten([{"active": True, "banned": False}], "users")
    row = result.primary_table.rows[0]
    assert row["active"] == 1
    assert row["banned"] == 0


def test_none_stays_none():
    result = flatten([{"email": None}], "users")
    assert result.primary_table.rows[0]["email"] is None


def test_nested_object_inlined():
    result = flatten([{"address": {"city": "NY", "zip": "10001"}}], "users")
    row = result.primary_table.rows[0]
    assert row["address_city"] == "NY"
    assert row["address_zip"] == "10001"


def test_array_of_primitives_serialized_as_json():
    result = flatten([{"tags": ["a", "b", "c"]}], "items")
    import json

    assert json.loads(result.primary_table.rows[0]["tags"]) == ["a", "b", "c"]


def test_array_of_objects_creates_child_table():
    result = flatten([{"id": 1, "orders": [{"oid": "o1"}, {"oid": "o2"}]}], "users")
    child = next(t for t in result.related_tables if "orders" in t.name)
    assert len(child.rows) == 2
    assert child.rows[0]["_index"] == 0
    assert child.rows[1]["_index"] == 1


def test_big_int_serialized_as_str():
    big = 2**54
    result = flatten([{"num": big}], "t")
    assert result.primary_table.rows[0]["num"] == str(big)


def test_empty_array_creates_empty_child_table():
    result = flatten([{"items": []}], "parent")
    child_names = [t.name for t in result.related_tables]
    assert any("items" in n for n in child_names)


def test_array_truncation_emits_warning():
    # Truncation only fires for arrays of objects (primitive arrays become JSON text)
    result = flatten([{"items": [{"x": i} for i in range(MAX_ARRAY_ROWS + 1)]}], "t")
    assert any(w.type == "array_truncated" for w in result.warnings)


def test_column_type_inference():
    result = flatten([{"val": 1}, {"val": 2}], "nums")
    col = next(c for c in result.primary_table.columns if c.name == "val")
    assert col.sqlite_type == "INTEGER"


def test_multiple_rows():
    data = [{"x": i} for i in range(5)]
    result = flatten(data, "t")
    assert len(result.primary_table.rows) == 5
