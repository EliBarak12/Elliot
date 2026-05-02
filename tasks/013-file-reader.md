# 013 — File Reader

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 005

## Objective
Read structured data from local files: CSV, JSON, and JSONL.

## Files to Create

### `packages/core/src/sources/file-reader.ts`

**`readFile(config: FileSourceConfig): Promise<FetchResult>`**

Supported formats:
- **CSV** — use `papaparse` with `header: true`, auto-detect delimiter, handle quoted fields and multi-line values
- **JSON** — parse file; if root is array use directly; if `{ data: [...] }` or `{ items: [...] }` extract array; otherwise wrap in array
- **JSONL** — read line by line, parse each line as JSON, collect into array; skip blank lines

Edge cases to handle:
- Empty file → return `FetchResult` with empty rows + warning
- File not found → throw `ElliotError('FILE_NOT_FOUND', ...)`
- Invalid JSON → throw `ElliotError('FILE_PARSE_ERROR', ...)`
- File > 100MB → emit `FlattenWarning` about size before processing

## Files to Create for Tests (fixtures used in task 015)
- `packages/core/tests/fixtures/customers.csv`
- `packages/core/tests/fixtures/orders.json`
- `packages/core/tests/fixtures/events.jsonl`

## Done When
- [ ] CSV with headers parsed correctly
- [ ] JSON array parsed correctly
- [ ] JSONL parsed correctly (one object per line)
- [ ] Empty file returns empty rows + warning (no throw)
