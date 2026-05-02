# 011 — SQLite Unit + Integration Tests

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 010

## Files to Create
- `packages/core/tests/unit/test_engine.py`
- `packages/core/tests/unit/test_query_runner.py`
- `packages/core/tests/integration/test_sqlite_engine.py`

## Required Tests

**test_engine.py:**
```python
def test_load_and_query() -> None: ...
def test_parameterized_query() -> None: ...
def test_empty_table_returns_empty_list() -> None: ...
def test_get_table_schema_returns_columns() -> None: ...
def test_profile_column_stats() -> None: ...
def test_close_raises_on_query() -> None: ...
```

**test_query_runner.py:**
```python
def test_valid_select_passes() -> None: ...
def test_drop_table_rejected() -> None: ...
def test_semicolon_rejected() -> None: ...
def test_pragma_rejected() -> None: ...
def test_comment_injection_safe() -> None:  # -- DROP TABLE ... -> valid
def test_named_params_bound_correctly() -> None: ...
def test_missing_param_raises() -> None: ...
```

**test_sqlite_engine.py (integration):**
```python
def test_three_table_join() -> None:
    # Load customers, orders, products
    # Run JOIN query, assert result has expected columns

def test_aggregate_query() -> None:
    # SUM(total) GROUP BY customer_id

def test_multi_param_query() -> None:
    # WHERE status = :status AND total > :min_total
```

## Done When
- [ ] All tests pass: `uv run pytest packages/core/tests/ -v`
- [ ] SQL injection attempts all rejected
