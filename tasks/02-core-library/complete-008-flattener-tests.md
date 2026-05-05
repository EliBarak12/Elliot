# 008 — Flattener Tests (pytest)

**Sprint**: 1 | **Estimate**: 3h | **Depends on**: 007

## Objective
Exhaustive pytest test suite for the JSON flattener. Minimum 17 test cases.

## Files to Create
- `packages/core/tests/unit/test_flattener.py`
- `packages/core/tests/unit/test_column_namer.py`
- `packages/core/tests/unit/test_type_inferrer.py`

## Required Test Cases (`test_flattener.py`)
```python
def test_flat_objects() -> None: ...
    # [{"id": 1, "name": "A"}] -> single table, 2 columns

def test_nested_object_inline() -> None: ...
    # {"user": {"id": 1}} -> column "user_id"

def test_array_of_objects_child_table() -> None: ...
    # {"tags": [{"name": "a"}]} -> child table with _parent_id

def test_array_of_primitives_json_text() -> None: ...
    # {"ids": [1, 2, 3]} -> TEXT column containing "[1, 2, 3]"

def test_depth_exceeded() -> None: ...
    # nesting depth > 5 -> TEXT column + depth_exceeded warning

def test_circular_reference() -> None: ...
    # circular ref -> "[Circular]" string + warning

def test_mixed_types_become_text() -> None: ...
    # column with int and str values -> TEXT

def test_reserved_keyword_renamed() -> None: ...
    # key "from" -> column "from_col"

def test_duplicate_names_get_suffix() -> None: ...
    # {"a_b": 1, "a": {"b": 2}} -> columns "a_b" and "a_b_2"

def test_empty_object_gives_null_row() -> None: ...
    # [{}] -> one row of all NULLs

def test_empty_array_creates_empty_table() -> None: ...
    # {"items": []} -> related table with 0 rows

def test_large_array_truncated() -> None: ...
    # array of 1500 objects -> 1000 rows + array_truncated warning

def test_null_values() -> None: ...
    # {"x": None} -> NULL in row

def test_boolean_becomes_int() -> None: ...
    # {"active": True} -> INTEGER 1

def test_large_int_becomes_text() -> None: ...
    # {"n": 2**54} -> TEXT

def test_unicode_key() -> None: ...
    # {"café": 1} -> safe ASCII column name

def test_three_level_nesting() -> None: ...
    # correct table hierarchy for 3-level nesting
```

## Done When
- [ ] All 17 tests pass: `uv run pytest packages/core/tests/unit/test_flattener.py -v`
- [ ] Coverage ≥ 85% on `elliot_core/sqlite/`
