# 015 — Source Fetcher Tests

**Sprint**: 1 | **Estimate**: 3h | **Depends on**: 012, 013, 014

## Objective
Integration tests for the API fetcher (using a local mock HTTP server) and unit tests for the file reader.

## Files to Create
- `packages/core/tests/integration/api-fetcher.test.ts`
- `packages/core/tests/unit/file-reader.test.ts`
- `packages/core/tests/unit/schema-detector.test.ts`

## Required Test Cases

**api-fetcher.test.ts** (use Node `http.createServer` as mock):
- Single-page fetch → returns all rows
- Cursor-paginated fetch → collects rows from all pages
- Rate-limited (first response is 429 with `Retry-After: 1`) → retries and succeeds
- Auth header present on all requests (validate server-side)
- Envelope unwrapping: `{ data: { items: [...] } }` → flat row array
- `maxPages` limit stops pagination at correct page count

**file-reader.test.ts** (use fixture files from task 013):
- `customers.csv` → correct row count and column names
- `orders.json` → nested array extracted correctly
- `events.jsonl` → each line parsed as separate object
- Empty CSV → empty rows + warning

**schema-detector.test.ts:**
- Mixed column types inferred correctly
- `schemaFingerprint` same hash on identical schemas
- Different column order → same fingerprint (sorted)

## Done When
- [ ] All integration tests pass against local mock server
- [ ] Auth values never appear in test output
