# 005 — Core Type Definitions (Pydantic)

**Sprint**: 1 | **Estimate**: 3h | **Depends on**: 004

## The Mental Model

A **Connector** represents a **business domain**, not a single API or database.

One connector can span any number of data sources — REST APIs, Postgres tables, MySQL tables, CSV files, JSON files — all within the same domain. A tool inside the connector can JOIN data from multiple sources in one query because Elliot ingests all required sources into an in-memory SQLite DB before executing the SQL.

```
Connector: "E-commerce Domain"
├── Source: products_api     (REST → https://api.shop.com/products)
├── Source: inventory_db     (Postgres → inventory table)
└── Source: categories_file  (CSV → ./data/categories.csv)

Tool: list_products_with_stock
  source_ids: ["products_api", "inventory_db"]
  sql: >
    SELECT p.name, p.price, i.quantity
    FROM products_api p
    JOIN inventory_db i ON p.id = i.product_id
    WHERE p.category = :category

Tool: get_category
  source_ids: ["categories_file"]
  sql: SELECT * FROM categories_file WHERE id = :id
```

Each source is ingested as a SQLite table named after its `id`. Tools declare which sources they need via `source_ids` — only those are fetched per call.

## Files to Create

### `packages/core/src/elliot_core/types/source.py`
```python
from pydantic import BaseModel, Field
from typing import Literal, Optional, Any

class AuthConfig(BaseModel):
    type: Literal["api_key", "bearer", "basic", "oauth2"]
    header_name: Optional[str] = None
    query_param: Optional[str] = None
    secret_key: str  # resolved via {{ env:VAR }} at load time

class PaginationConfig(BaseModel):
    strategy: Literal["cursor", "offset", "page", "link_header", "none"] = "none"
    page_size: int = 100
    max_pages: int = 100
    cursor_field: Optional[str] = None
    next_url_field: Optional[str] = None

class SourceConfig(BaseModel):
    id: str                    # used as the SQLite table name for this source
    name: str
    type: Literal["rest", "postgres", "mysql", "file"]

    # REST sources
    url: Optional[str] = None
    method: Literal["GET", "POST"] = "GET"
    auth: Optional[AuthConfig] = None
    pagination: PaginationConfig = PaginationConfig()
    data_path: Optional[str] = None   # jmespath to extract list from response
    timeout_ms: int = 30_000

    # DB sources (postgres / mysql)
    table: Optional[str] = None       # table to SELECT * from, OR
    query: Optional[str] = None       # raw SQL to run on the upstream DB

    # File sources
    path: Optional[str] = None
    format: Optional[Literal["csv", "json", "jsonl"]] = None
    encoding: str = "utf-8"
    delimiter: str = ","

class FetchWarning(BaseModel):
    type: str
    message: str
    field: Optional[str] = None

class FetchResult(BaseModel):
    rows: list[dict[str, Any]]
    warnings: list[FetchWarning] = []
    fetched_at: str    # ISO timestamp
    page_count: int = 1
```

### `packages/core/src/elliot_core/types/tool.py`
```python
from pydantic import BaseModel
from typing import Literal, Optional, Any

class ParameterDefinition(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean", "date"]
    required: bool = True
    description: str = ""
    default: Optional[Any] = None

class ResponseShape(BaseModel):
    fields: Optional[list[str]] = None   # keep only these columns
    rename: dict[str, str] = {}          # old_name → new_name
    max_rows: int = 1000

class ToolDefinition(BaseModel):
    id: str
    name: str
    description: str
    category: Literal["READ", "WRITE", "ACTION"]

    # Which sources to fetch and ingest into SQLite before running sql.
    # Each source.id becomes a SQLite table name.
    # A tool may reference one source or JOIN across many.
    source_ids: list[str]

    sql: str                             # runs against the in-memory SQLite
    parameters: list[ParameterDefinition] = []
    response_shape: ResponseShape = ResponseShape()

class SkillStep(BaseModel):
    alias: str
    tool_id: str
    params: dict[str, Any]  # may contain {{skill.input.X}} or {{steps.Y.Z}}

class SkillDefinition(BaseModel):
    id: str
    name: str
    description: str
    steps: list[SkillStep]
    input_parameters: list[ParameterDefinition] = []

class ToolResult(BaseModel):
    rows: list[dict[str, Any]]
    meta: dict[str, Any]   # row_count, latency_ms, truncated, sources_fetched
```

### `packages/core/src/elliot_core/types/connector.py`
```python
from pydantic import BaseModel, model_validator
from typing import Optional

class ConnectorConfig(BaseModel):
    name: str
    slug: str
    version: str
    description: str = ""
    sources: list[SourceConfig] = []
    tools: list[ToolDefinition] = []
    skills: list[SkillDefinition] = []
    rate_limit: int = 60

    @model_validator(mode="after")
    def _validate_source_refs(self) -> "ConnectorConfig":
        """Every source_id referenced in a tool must exist in sources."""
        source_ids = {s.id for s in self.sources}
        for tool in self.tools:
            for sid in tool.source_ids:
                if sid not in source_ids:
                    raise ValueError(
                        f"Tool '{tool.id}' references unknown source '{sid}'. "
                        f"Available: {sorted(source_ids)}"
                    )
        return self
```

### `packages/core/src/elliot_core/types/sqlite.py`
```python
class ColumnMeta(BaseModel):
    name: str
    sqlite_type: Literal["INTEGER", "REAL", "TEXT"]
    nullable: bool = True

class FlattenedTable(BaseModel):
    name: str          # matches source.id — becomes the SQLite table name
    columns: list[ColumnMeta]
    rows: list[dict[str, Any]]

class FlattenResult(BaseModel):
    tables: list[FlattenedTable]     # one per source fetched
    warnings: list[FetchWarning] = []
```

### `packages/core/src/elliot_core/types/audit.py`
```python
class AuditLogEntry(BaseModel):
    timestamp: str
    tool_id: str
    session_id: str
    params: dict[str, str]   # values redacted
    sources_fetched: list[str]
    row_count: int
    latency_ms: float
    error: Optional[str] = None
```

## Example: Multi-source connector JSON

```json
{
  "name": "E-commerce Domain",
  "slug": "ecommerce",
  "version": "1.0.0",
  "sources": [
    {
      "id": "products_api",
      "type": "rest",
      "url": "https://api.shop.com/products",
      "data_path": "data.items",
      "auth": {"type": "bearer", "secret_key": "{{ env:SHOP_API_TOKEN }}"}
    },
    {
      "id": "inventory_db",
      "type": "postgres",
      "url": "{{ env:PG_URL }}",
      "table": "inventory"
    },
    {
      "id": "categories_file",
      "type": "file",
      "path": "./data/categories.csv",
      "format": "csv"
    }
  ],
  "tools": [
    {
      "id": "list_products_with_stock",
      "name": "List products with stock level",
      "description": "Return products filtered by category, joined with live inventory levels",
      "category": "READ",
      "source_ids": ["products_api", "inventory_db"],
      "sql": "SELECT p.name, p.price, i.quantity FROM products_api p JOIN inventory_db i ON p.id = i.product_id WHERE (:category IS NULL OR p.category = :category) LIMIT 50",
      "parameters": [
        {"name": "category", "type": "string", "required": false, "description": "Filter by product category"}
      ]
    },
    {
      "id": "get_category_info",
      "name": "Get category information",
      "description": "Return metadata for a product category from the reference file",
      "category": "READ",
      "source_ids": ["categories_file"],
      "sql": "SELECT * FROM categories_file WHERE id = :id",
      "parameters": [
        {"name": "id", "type": "string", "required": true, "description": "Category ID"}
      ]
    }
  ]
}
```

## Done When
- [ ] All models importable from `elliot_core.types`
- [ ] `ConnectorConfig` validator rejects unknown `source_ids` with a clear error
- [ ] `ToolDefinition.source_ids` is required and non-empty
- [ ] `uv run mypy packages/core/src` exits 0
