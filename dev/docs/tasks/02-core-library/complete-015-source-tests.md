# 015 — Source Fetcher Tests

**Sprint**: 1 | **Estimate**: 3h | **Depends on**: 012, 013, 014

## Files to Create
- `packages/core/tests/integration/test_api_fetcher.py`
- `packages/core/tests/unit/test_file_reader.py`
- `packages/core/tests/unit/test_schema_detector.py`

## test_api_fetcher.py (use `respx` to mock httpx)
```python
import respx, httpx, pytest
from elliot_core.sources.api_fetcher import fetch_endpoint

@pytest.mark.asyncio
async def test_single_page_fetch() -> None:
    with respx.mock:
        respx.get("http://api.test/items").mock(return_value=httpx.Response(200, json=[{"id": 1}]))
        result = await fetch_endpoint(config, secrets={})
        assert len(result.rows) == 1

async def test_cursor_pagination_collects_all_pages() -> None: ...
async def test_rate_limit_retry() -> None:
    # First call returns 429 with Retry-After: 0, second returns 200
async def test_auth_header_injected() -> None:
    # Assert header present on request (respx captures it)
async def test_envelope_unwrapping() -> None:
    # {"data": {"items": [...]}} -> rows extracted
async def test_max_pages_stops_pagination() -> None: ...
```

## test_file_reader.py
```python
def test_csv_fixture() -> None: ...
def test_json_array_direct() -> None: ...
def test_json_envelope_extracted() -> None: ...
def test_jsonl_fixture() -> None: ...
def test_empty_csv_returns_warning() -> None: ...
def test_missing_file_raises() -> None: ...
```

## test_schema_detector.py
```python
def test_type_inference_correct() -> None: ...
def test_fingerprint_stable() -> None: ...
def test_fingerprint_order_independent() -> None:
    # Same cols in different order -> same fingerprint
```

## Done When
- [ ] All tests pass without network access (respx mocks all HTTP)
- [ ] `uv run pytest packages/core/tests/ -v` exits 0
