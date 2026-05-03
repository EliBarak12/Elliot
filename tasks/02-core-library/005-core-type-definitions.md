# 005 — Core Type Definitions (Pydantic)

**Sprint**: 1 | **Estimate**: 3h | **Depends on**: 004

## Objective
All shared data models as Pydantic v2 `BaseModel` classes. Single source of truth for every data shape.

## Files to Create

### `packages/core/src/elliot_core/types/source.py`
```python
from pydantic import BaseModel, Field
from typing import Literal, Optional, Any

class AuthConfig(BaseModel):
    type: Literal["api_key", "bearer", "basic", "oauth2"]
    header_name: Optional[str] = None
    query_param: Optional[str] = None
    secret_key: str  # key into encrypted secrets dict

class PaginationConfig(BaseModel):
    strategy: Literal["cursor", "offset", "page", "link_header", "none"] = "none"
    page_size: int = 100
    max_pages: int = 100
    cursor_field: Optional[str] = None
    next_url_field: Optional[str] = None

class ApiEndpointConfig(BaseModel):
    url: str
    method: Literal["GET", "POST"] = "GET"
    auth: Optional[AuthConfig] = None
    pagination: PaginationConfig = PaginationConfig()
    timeout_ms: int = 30_000
    envelope_path: Optional[str] = None  # e.g. "data.items"
    refresh_strategy: Literal["always", "cache_1h", "cache_1d"] = "always"

class FileSourceConfig(BaseModel):
    path: str
    format: Literal["csv", "json", "jsonl"]
    encoding: str = "utf-8"
    delimiter: str = ","  # CSV only

class DbSourceConfig(BaseModel):
    db_type: Literal["sqlite", "postgres"]
    connection_secret_key: str  # key into secrets
    sql: str

class FetchWarning(BaseModel):
    type: str
    message: str
    field: Optional[str] = None

class FetchResult(BaseModel):
    rows: list[dict[str, Any]]
    warnings: list[FetchWarning] = []
    fetched_at: str  # ISO timestamp
    page_count: int = 1
```

### `packages/core/src/elliot_core/types/tool.py`
```python
class ParameterDefinition(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean", "date"]
    required: bool = True
    description: str = ""
    default: Optional[Any] = None

class ResponseShape(BaseModel):
    fields: Optional[list[str]] = None  # keep only these fields
    rename: dict[str, str] = {}         # old_name -> new_name
    max_rows: int = 1000

class ToolDefinition(BaseModel):
    id: str
    name: str  # snake_case
    description: str
    category: Literal["READ", "ACTION", "AGGREGATE"]
    sql: str
    parameters: list[ParameterDefinition] = []
    response_shape: ResponseShape = ResponseShape()
    include_metadata: bool = True

class SkillStep(BaseModel):
    alias: str
    tool_name: str
    params: dict[str, Any]  # may contain {{skill.input.X}} or {{steps.Y.Z}} templates

class SkillDefinition(BaseModel):
    id: str
    name: str
    description: str
    steps: list[SkillStep]
    input_parameters: list[ParameterDefinition] = []

class ToolResult(BaseModel):
    rows: list[dict[str, Any]]
    meta: dict[str, Any]  # rowCount, latencyMs, truncated
```

### `packages/core/src/elliot_core/types/connector.py`
```python
class ProductContext(BaseModel):
    name: str
    domain: str
    description: str = ""
    audience: str = ""

class SourceConfig(BaseModel):
    id: str
    name: str
    type: Literal["api", "file", "db", "rest", "postgres", "mysql"]
    url: str
    table: Optional[str] = None
    query: Optional[str] = None
    data_path: Optional[str] = None  # jmespath to extract list from REST response
    auth: Optional[AuthConfig] = None

class ConnectorConfig(BaseModel):
    name: str
    slug: str
    version: str
    description: str = ""
    sources: list[SourceConfig] = []
    tools: list[ToolDefinition] = []
    skills: list[SkillDefinition] = []
    rate_limit: int = 60
```

### `packages/core/src/elliot_core/types/sqlite.py`
```python
class ColumnMeta(BaseModel):
    name: str
    sqlite_type: Literal["INTEGER", "REAL", "TEXT"]
    nullable: bool = True
    format_hint: Optional[str] = None  # iso_date, uuid, email

class FlattenedTable(BaseModel):
    name: str
    columns: list[ColumnMeta]
    rows: list[dict[str, Any]]

class FlattenResult(BaseModel):
    primary_table: FlattenedTable
    related_tables: list[FlattenedTable] = []
    warnings: list[FetchWarning] = []

class FlattenWarning(BaseModel):
    type: Literal["depth_exceeded", "array_truncated", "circular_ref", "reserved_keyword", "name_collision"]
    field_path: str
    message: str
```

### `packages/core/src/elliot_core/types/audit.py`
```python
class AuditLogEntry(BaseModel):
    timestamp: str
    tool_name: str
    session_id: str
    params: dict[str, str]  # redacted values
    row_count: int
    latency_ms: float
    error: Optional[str] = None
```

### `packages/core/src/elliot_core/types/evaluation.py`
```python
class EvalCase(BaseModel):
    id: str
    description: str
    tool_name: str
    params: dict[str, Any]
    expected_rows: Optional[list[dict[str, Any]]] = None
    expected_shape: Optional[dict[str, Any]] = None
    match_type: Literal["exact", "shape", "contains"] = "contains"

class EvalSuite(BaseModel):
    id: str
    name: str
    cases: list[EvalCase]

class EvalCaseResult(BaseModel):
    case_id: str
    passed: bool
    actual_rows: list[dict[str, Any]]
    latency_ms: float
    error: Optional[str] = None

class EvalRunResult(BaseModel):
    suite_id: str
    run_at: str
    score: float  # 0-100
    passed: int
    failed: int
    cases: list[EvalCaseResult]
```

## Done When
- [ ] All models importable from their modules
- [ ] `uv run mypy packages/core/src` exits 0
- [ ] No `Any` in model fields without explicit annotation
