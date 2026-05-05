# 012 — API Fetcher (httpx)

**Sprint**: 1 | **Estimate**: 4h | **Depends on**: 005

## Files to Create

### `packages/core/src/elliot_core/sources/api_fetcher.py`

```python
import httpx
import asyncio
import time
from elliot_core.types.source import ApiEndpointConfig, FetchResult, FetchWarning

async def fetch_endpoint(
    config: ApiEndpointConfig,
    secrets: dict[str, str],
) -> FetchResult:
    """Fetch all pages from a REST API endpoint."""
    ...
```

**Implement all of:**
1. **Auth injection** — based on `config.auth.type`:
   - `api_key` → inject into header `config.auth.header_name` or query param
   - `bearer` → `Authorization: Bearer <secret>`
   - `basic` → base64 encode `user:pass` from secrets
   - Never log the actual secret value
2. **Envelope unwrapping** — if response is `{"data": [...]}`, `{"items": [...]}`, `{"results": [...]}` extract the list. If root is already a list, use directly.
3. **Pagination** via `config.pagination.strategy`:
   - `cursor`: read `next_cursor` / `cursor` field from response, set as `?cursor=` param
   - `offset`: increment by `page_size` until empty page
   - `page`: increment `?page=` until empty
   - `link_header`: parse `Link: <url>; rel="next"` HTTP header
   - Stop after `config.pagination.max_pages` pages
4. **Retry** on 429 (read `Retry-After` header, default 5s), 500, 503 — up to 3 attempts
5. **Timeout**: `config.timeout_ms / 1000` seconds via `httpx.AsyncClient(timeout=...)`

### `packages/core/src/elliot_core/sources/paginator.py`
Helper class managing pagination state for each strategy.

## Done When
- [ ] Single-page GET returns rows
- [ ] Cursor pagination collects all pages
- [ ] 429 triggers retry after delay
- [ ] Secret values absent from any exception message
