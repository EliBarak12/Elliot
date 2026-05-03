# 014 — DB Connector

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 005

## Files to Create

### `packages/core/src/elliot_core/sources/db_connector.py`
```python
import sqlite3
from elliot_core.types.source import DbSourceConfig, FetchResult
from elliot_core.sqlite.query_runner import validate_tool_sql
from elliot_core.errors import ElliotError

def query_database(
    config: DbSourceConfig,
    secrets: dict[str, str],
) -> FetchResult:
    ...
```

**Supported DB types:**
- **`sqlite`**: open file with `sqlite3.connect(path, uri=True)` + `?mode=ro` (read-only), execute `config.sql`, return rows as `list[dict]`
- **`postgres`**: connect with `psycopg2.connect(secrets[config.connection_secret_key])`, set `autocommit=False`, execute `BEGIN READ ONLY; <sql>; COMMIT`, return rows. Set `options='-c statement_timeout=30000'`.

**Safety:**
- Validate `config.sql` with `validate_tool_sql()` before executing → raise `ElliotError("INVALID_SQL")` if fails
- Never log connection strings

### `packages/core/src/elliot_core/sources/schema_detector.py`
```python
import hashlib, json
from elliot_core.types.sqlite import ColumnMeta
from elliot_core.sqlite.type_inferrer import infer_column_type, detect_format

def detect_schema(rows: list[dict]) -> list[ColumnMeta]: ...
def schema_fingerprint(cols: list[ColumnMeta]) -> str:
    """SHA-256 of sorted column names+types. Stable across runs."""
    key = json.dumps(sorted((c.name, c.sqlite_type) for c in cols))
    return hashlib.sha256(key.encode()).hexdigest()
```

## Done When
- [ ] SQLite file query returns correct rows
- [ ] Non-SELECT SQL rejected before execution
- [ ] `schema_fingerprint` is identical across two calls with same schema
