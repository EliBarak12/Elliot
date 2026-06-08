from elliot_core.sqlite.column_namer import MAX_IDENTIFIER_LENGTH
from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.sqlite.flattener import MAX_ARRAY_ROWS, flatten


def test_deeply_nested_object_columns_stay_within_identifier_limit():
    """Regression: a deeply nested object (as real APIs like pokeapi return)
    inlines into composite column names that exceed SQLite's 63-char identifier
    limit. The flattener must bound them so the engine can CREATE TABLE instead
    of aborting the whole discovery with INVALID_IDENTIFIER."""
    payload = {
        "id": 1,
        "sprites": {
            "versions": {
                "generation_viii": {
                    "brilliant_diamond_shining_pearl": {
                        "front_default": "a.png",
                        "front_shiny_female": "b.png",
                    }
                }
            }
        },
    }
    result = flatten([payload], "monster")
    all_tables = [result.primary_table, *result.related_tables]
    for table in all_tables:
        assert len(table.name) <= MAX_IDENTIFIER_LENGTH
        for col in table.columns:
            assert len(col.name) <= MAX_IDENTIFIER_LENGTH, col.name
    # The engine actually accepts every table the flattener produced.
    engine = SQLiteEngine()
    for table in all_tables:
        engine.load_table(table)
    # Row keys were rewritten in lock-step with the schema, so the bounded
    # deep column is still backed by a real value.
    assert set(result.primary_table.rows[0].keys()) == {
        c.name for c in result.primary_table.columns
    }


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


def test_array_with_nested_lists_does_not_leave_lists_in_rows():
    """Regression: nested arrays used to land in rows as raw Python lists,
    which then blew up sqlite parameter binding with 'type list is not
    supported'. They must be JSON-encoded instead."""
    import json

    result = flatten(
        [{"matrix": [[1, 2], [3, 4]]}],
        "t",
    )
    # Whether the value lands on the primary row or in a child table, no row
    # value anywhere in the result may be a raw list or dict.
    all_rows = list(result.primary_table.rows) + [r for t in result.related_tables for r in t.rows]
    for row in all_rows:
        for value in row.values():
            assert not isinstance(value, (list, dict)), (
                f"row value {value!r} is unbindable for sqlite"
            )

    # And the JSON-encoded form must round-trip back to the original.
    primary_or_child = [row for row in all_rows if row.get("value")]
    assert primary_or_child, "expected nested array contents to survive"
    decoded = [json.loads(r["value"]) for r in primary_or_child if isinstance(r["value"], str)]
    assert [1, 2] in decoded and [3, 4] in decoded


def test_array_of_mixed_dicts_and_primitives_serializes_primitives_safely():
    result = flatten(
        [{"items": [{"k": "v"}, "primitive", 42]}],
        "t",
    )
    child = next(t for t in result.related_tables if "items" in t.name)
    for row in child.rows:
        for value in row.values():
            assert not isinstance(value, (list, dict)), (
                f"unbindable list/dict leaked into child row: {value!r}"
            )
