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


def test_two_keys_normalizing_to_same_name_both_preserved():
    """Sacred-cow regression: ``my-col`` and ``my_col`` both normalize to
    ``my_col`` via safe_name. Before disambiguation the second silently
    overwrote the first in the row dict, dropping data."""
    result = flatten([{"my-col": 1, "my_col": 2}], "t")
    row = result.primary_table.rows[0]
    col_names = [c.name for c in result.primary_table.columns]

    assert "my_col" in row
    assert "my_col_2" in row
    # Both values present, neither is None.
    assert row["my_col"] is not None
    assert row["my_col_2"] is not None
    assert {row["my_col"], row["my_col_2"]} == {1, 2}
    # Schema matches row keys exactly.
    assert "my_col" in col_names
    assert "my_col_2" in col_names


def test_nested_flat_form_collides_with_top_level_sibling():
    """``{'a': {'b': 1}, 'a_b': 2}`` inlines to ``a_b`` and ``a_b``;
    both values must survive."""
    result = flatten([{"a": {"b": 1}, "a_b": 2}], "t")
    row = result.primary_table.rows[0]
    col_names = [c.name for c in result.primary_table.columns]

    assert "a_b" in row
    assert "a_b_2" in row
    assert {row["a_b"], row["a_b_2"]} == {1, 2}
    assert "a_b" in col_names
    assert "a_b_2" in col_names


def test_three_way_collision_all_preserved():
    """Three source keys all normalize to ``foo_bar``."""
    result = flatten([{"foo-bar": 1, "foo_bar": 2, "foo.bar": 3}], "t")
    row = result.primary_table.rows[0]
    col_names = [c.name for c in result.primary_table.columns]

    assert {"foo_bar", "foo_bar_2", "foo_bar_3"} <= set(row.keys())
    assert {row["foo_bar"], row["foo_bar_2"], row["foo_bar_3"]} == {1, 2, 3}
    assert {"foo_bar", "foo_bar_2", "foo_bar_3"} <= set(col_names)


def test_collision_round_trip_via_sqlite_engine():
    """End-to-end: load the flattened table into SQLite and read both
    values back. This is the contract the rest of the system relies on."""
    from elliot_core.sqlite.engine import SQLiteEngine

    result = flatten([{"my-col": "first", "my_col": "second"}], "t")
    engine = SQLiteEngine()
    try:
        engine.load_result(result)
        rows = engine.query("SELECT my_col, my_col_2 FROM t")
        assert len(rows) == 1
        assert {rows[0]["my_col"], rows[0]["my_col_2"]} == {"first", "second"}
    finally:
        engine.close()


def test_empty_input_no_regression():
    result = flatten([], "t")
    assert result.primary_table.rows == []
    assert result.primary_table.columns == []


def test_scalar_input_wrapped_in_value_column():
    """Top-level non-dict items get wrapped under a ``value`` column."""
    result = flatten([42, "hi", None], "t")
    assert len(result.primary_table.rows) == 3
    assert result.primary_table.rows[0]["value"] == 42
    assert result.primary_table.rows[1]["value"] == "hi"
    assert result.primary_table.rows[2]["value"] is None


def test_list_of_scalars_at_top_level_no_regression():
    result = flatten([{"tags": [1, 2, 3]}], "t")
    import json as _json

    row = result.primary_table.rows[0]
    assert _json.loads(row["tags"]) == [1, 2, 3]


def test_collision_logs_warning(capsys):
    """Disambiguation must emit a structlog warning — count only, no values."""
    result = flatten([{"my-col": "secret-a", "my_col": "secret-b"}], "t")
    # Both values still present (sanity).
    assert {result.primary_table.rows[0]["my_col"], result.primary_table.rows[0]["my_col_2"]} == {
        "secret-a",
        "secret-b",
    }
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "flatten.column_collision_disambiguated" in output
    assert "collisions=1" in output
    # Sacred-cow: the warning never includes the colliding *values*.
    assert "secret-a" not in output
    assert "secret-b" not in output


def test_no_collision_no_warning(capsys):
    """Routine flattens must not spam the log."""
    flatten([{"a": 1, "b": 2, "c": 3}], "t")
    captured = capsys.readouterr()
    assert "column_collision_disambiguated" not in (captured.out + captured.err)
