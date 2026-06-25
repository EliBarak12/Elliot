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


def test_hebrew_columns_preserved_no_data_loss():
    # Regression for P1: non-ASCII headers used to all collapse to "col" and
    # all but one column's data was silently dropped.
    data = [
        {"שם": "דנה", "עיר": "תל אביב", "מספר רישיון": 123},
        {"שם": "יוסי", "עיר": "חיפה", "מספר רישיון": 456},
    ]
    result = flatten(data, "doctors")
    cols = [c.name for c in result.primary_table.columns]
    assert "שם" in cols and "עיר" in cols and "מספר_רישיון" in cols
    row = result.primary_table.rows[0]
    assert row["שם"] == "דנה"
    assert row["עיר"] == "תל אביב"
    assert row["מספר_רישיון"] == 123
    # No collision among distinct Hebrew names -> no rename warning.
    assert not [w for w in result.warnings if w.type == "column_renamed"]


def test_colliding_columns_are_kept_and_warned():
    # Two keys that normalize to the same safe name must both survive, with a
    # warning instead of silent overwrite.
    result = flatten([{"Name": "a", "name ": "b"}], "t")
    cols = [c.name for c in result.primary_table.columns]
    assert "name" in cols and "name_2" in cols
    row = result.primary_table.rows[0]
    assert row["name"] == "a" and row["name_2"] == "b"
    renamed = [w for w in result.warnings if w.type == "column_renamed"]
    assert len(renamed) == 1  # de-duped to one warning, not one per row
