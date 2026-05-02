# 012 — API Fetcher

**Sprint**: 1 | **Estimate**: 4h | **Depends on**: 005

## Objective
Fetch data from REST APIs with auth injection, pagination, and retry logic.

## Files to Create

### `packages/core/src/sources/api-fetcher.ts`

**`fetchEndpoint(config: ApiEndpointConfig, secrets: Record<string, string>): Promise<FetchResult>`**

Implement:
1. **Auth injection** — inject into headers/query/body based on `config.auth.type` (`api_key`, `bearer`, `basic`, `oauth2`). Never log the actual credential value.
2. **Response envelope unwrapping** — if response is `{ data: [...] }` or `{ items: [...] }` or `{ results: [...] }` extract the array. If root is already an array, use as-is.
3. **Pagination** strategies:
   - `cursor` — follow `nextCursor` / `next_cursor` field until null
   - `offset` — increment by page size until empty page
   - `page` — increment page number until empty
   - `link_header` — follow HTTP `Link: <url>; rel="next"` header
4. **Hard limit**: stop after `config.pagination.maxPages` (default 100) pages
5. **Retry** on HTTP 429 (respect `Retry-After` header), 500, 503 — up to 3 attempts with exponential backoff
6. **Timeout**: respect `config.timeoutMs` (default 30000)

### `packages/core/src/sources/paginator.ts`
Helper that encapsulates pagination state for each strategy.

## Done When
- [ ] Single-page fetch returns correct rows
- [ ] Cursor pagination collects all pages
- [ ] 429 retry waits `Retry-After` seconds and retries
- [ ] Auth header value never appears in any log output
