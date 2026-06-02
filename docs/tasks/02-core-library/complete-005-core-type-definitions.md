# 005 — Core Type Definitions (Pydantic)

**Sprint**: 1 | **Estimate**: 3h | **Depends on**: 004

## The Mental Model

A **Connector** represents a **business domain**, not a single API or database. One connector can span REST APIs, Postgres tables, MySQL tables, CSV and JSON files.

**The agent (or user) never writes SQL or HTTP requests directly.** They define a tool using high-level concepts:
- Which source(s) to pull data from
- Which filters to apply (field, operator, parameter or fixed value)
- Which fields to return (with optional aggregation)
- For REST write operations: which parameters map to the HTTP request

Elliot’s execution engine converts this into a safe parameterized SQL query (for DB/file sources) or an HTTP call (for REST sources) at runtime.

```
Connector: "E-commerce Domain"
├── Source: products_api     REST  → https://api.shop.com/products
├── Source: inventory_db     Postgres → inventory table
└── Source: categories_file  CSV → ./data/categories.csv

Tool: list_products_with_stock
  source_ids:    [products_api, inventory_db]
  filter_groups: [species = :category]        ← agent passes this at call time
  return_fields: [name, price, quantity]       ← Elliot generates the JOIN + SELECT
  limit:         50
```

## Files to Create

### `packages/core/src/elliot_core/types/source.py`
```python
from pydantic import BaseModel
from typing import Literal, Optional, Any

class AuthConfig(BaseModel):
    type: Literal["api_key", "bearer", "basic", "oauth2"]
    header_name: Optional[str] = None
    query_param: Optional[str] = None
    secret_key: str  # resolved via {{ env:VAR }} at load time

class PaginationConfig(BaseModel):
    strategy: Literal["cursor", "offset", "page", "link_header", "none"] = "none"
    page_size: int = 100
    max_pages: int = 10
    cursor_field: Optional[str] = None
    next_url_field: Optional[str] = None

class SourceConfig(BaseModel):
    id: str           # becomes the table name in SQLite (for DB/file) or the source key (for REST)
    name: str
    type: Literal["rest", "postgres", "mysql", "file"]

    # REST
    url: Optional[str] = None
    method: Literal["GET", "POST"] = "GET"
    auth: Optional[AuthConfig] = None
    pagination: PaginationConfig = PaginationConfig()
    data_path: Optional[str] = None   # jmespath to extract list from response
    timeout_ms: int = 30_000

    # DB (postgres / mysql)
    table: Optional[str] = None       # fetch all rows from this table
    query: Optional[str] = None       # or run this read-only query on the upstream DB

    # File
    path: Optional[str] = None
    format: Optional[Literal["csv", "json", "jsonl"]] = None
    encoding: str = "utf-8"
    delimiter: str = ","

class FetchResult(BaseModel):
    rows: list[dict[str, Any]]
    fetched_at: str
    page_count: int = 1
    warnings: list[str] = []
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

class FilterCondition(BaseModel):
    field: str
    operator: Literal["=", "!=", ">", ">=", "<", "<=", "in_list", "contains", "is_null", "is_not_null"]
    value: Optional[Any] = None            # fixed value baked into the tool
    parameter_name: Optional[str] = None   # runtime parameter passed by the agent

class FilterGroup(BaseModel):
    logic: Literal["AND", "OR"] = "AND"
    conditions: list[FilterCondition] = []

class ReturnField(BaseModel):
    field: str
    alias: Optional[str] = None
    aggregation: Literal["none", "count", "sum", "avg", "min", "max"] = "none"

class ApiRequestMapping(BaseModel):
    """
    For REST sources: how tool parameters map into the HTTP request.
    Only used when source.type == 'rest' and category == 'WRITE' or 'ACTION'.
    """
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = "POST"
    path_template: Optional[str] = None   # e.g. "/users/{user_id}" — {param} interpolated
    query_params: list[str] = []          # parameter names sent as query string
    body_params: list[str] = []           # parameter names sent in JSON body
    body_format: Literal["json", "form"] = "json"

class ResponseShape(BaseModel):
    max_rows: int = 1000
    rename: dict[str, str] = {}           # old_name → new_name in output

class ToolDefinition(BaseModel):
    id: str
    name: str
    description: str
    category: Literal["READ", "WRITE", "ACTION"]

    # Which sources to pull data from.
    # Each source.id becomes a SQLite table name (for DB/file) or the base URL (for REST).
    source_ids: list[str]

    # ── READ tools (DB / file sources) ─────────────────────────────────
    # Elliot converts these into a safe parameterized SELECT.
    filter_groups: list[FilterGroup] = []
    return_fields: list[ReturnField] = []
    limit: int = 100

    # ── WRITE / ACTION tools (REST sources) ───────────────────────────
    # Elliot maps parameters into the HTTP request body / query string.
    api_mapping: Optional[ApiRequestMapping] = None

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
from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import ToolDefinition, SkillDefinition

class ConnectorConfig(BaseModel):
    name: str
    slug: str
    version: str
    description: str = ""
    sources: list[SourceConfig] = []
    tools: list[ToolDefinition] = []
    skills: list[SkillDefinition] = []

    @model_validator(mode="after")
    def _validate_source_refs(self) -> "ConnectorConfig":
        source_ids = {s.id for s in self.sources}
        for tool in self.tools:
            for sid in tool.source_ids:
                if sid not in source_ids:
                    raise ValueError(
                        f"Tool '{tool.id}' references unknown source '{sid}'. "
                        f"Available: {sorted(source_ids)}"
                    )
            if tool.category == "READ" and not tool.source_ids:
                raise ValueError(f"READ tool '{tool.id}' must declare at least one source_id")
        return self
```

## Example connector.json

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
      "auth": {"type": "bearer", "secret_key": "{{ env:SHOP_TOKEN }}"}
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
      "description": "Return products joined with live inventory, optionally filtered by category",
      "category": "READ",
      "source_ids": ["products_api", "inventory_db"],
      "filter_groups": [
        {
          "logic": "AND",
          "conditions": [
            {"field": "products_api.category", "operator": "=", "parameter_name": "category"}
          ]
        }
      ],
      "return_fields": [
        {"field": "products_api.name"},
        {"field": "products_api.price"},
        {"field": "inventory_db.quantity"}
      ],
      "limit": 50,
      "parameters": [
        {"name": "category", "type": "string", "required": false, "description": "Filter by product category"}
      ]
    },
    {
      "id": "create_order",
      "name": "Create an order",
      "description": "Submit a new order to the orders API with the specified product and quantity",
      "category": "WRITE",
      "source_ids": ["products_api"],
      "api_mapping": {
        "method": "POST",
        "path_template": "/orders",
        "body_params": ["product_id", "quantity", "customer_id"],
        "body_format": "json"
      },
      "parameters": [
        {"name": "product_id", "type": "string", "required": true, "description": "Product ID to order"},
        {"name": "quantity", "type": "integer", "required": true, "description": "Number of units"},
        {"name": "customer_id", "type": "string", "required": true, "description": "Customer placing the order"}
      ]
    }
  ]
}
```

## Done When
- [ ] All models importable from `elliot_core.types`
- [ ] `ConnectorConfig` validator rejects unknown `source_ids`
- [ ] `ToolDefinition` with `filter_groups` + `return_fields` validates correctly
- [ ] `ToolDefinition` with `api_mapping` validates correctly
- [ ] `uv run mypy packages/core/src` exits 0
