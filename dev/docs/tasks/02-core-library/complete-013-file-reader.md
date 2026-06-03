# 013 — File Reader

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 005

## Files to Create

### `packages/core/src/elliot_core/sources/file_reader.py`
```python
import csv
import json
from pathlib import Path
from elliot_core.types.source import FileSourceConfig, FetchResult, FetchWarning
from elliot_core.errors import ElliotError

def read_file(config: FileSourceConfig) -> FetchResult:
    """Read structured data from a local file (CSV, JSON, or JSONL)."""
    path = Path(config.path)
    if not path.exists():
        raise ElliotError("FILE_NOT_FOUND", f"File not found: {config.path}")
    ...
```

**Format handling:**
- **CSV**: `csv.DictReader` with `config.delimiter`, encoding `config.encoding`. Each row is a `dict[str, str]`.
- **JSON**: `json.loads(path.read_text())`. If root is list → use directly. If `{"data": [...]}` or `{"items": [...]}` → extract. Else wrap in list.
- **JSONL**: read line by line, `json.loads(line)` per non-empty line.

**Edge cases:**
- Empty file → return empty rows + `FetchWarning(type="empty_file", ...)`
- File > 100MB → emit size warning before processing
- `json.JSONDecodeError` → raise `ElliotError("FILE_PARSE_ERROR", ...)`

## Fixture Files to Create
- `packages/core/tests/fixtures/customers.csv` (5+ rows, columns: id, name, email, status, total_spent)
- `packages/core/tests/fixtures/orders.json` (list of orders with nested items array)
- `packages/core/tests/fixtures/events.jsonl` (5+ JSON lines)

## Done When
- [ ] CSV parsed with correct column names and row count
- [ ] JSON array extracted from `{"data": [...]}` envelope
- [ ] JSONL: each line is a separate dict in result
- [ ] Missing file raises `ElliotError("FILE_NOT_FOUND")`
