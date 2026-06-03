# 055 — End-to-End Integration Test

**Sprint**: 4 | **Estimate**: 3h | **Depends on**: 037, 032

## Objective
Single pytest test that exercises the complete flow in-process: CSV source → tool definition → connector export → runtime load → tool execution.

## File to Create

### `packages/connector-runtime/tests/integration/test_e2e_flow.py`
```python
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from elliot_core.connector.builder import ConnectorBuilder
from elliot_core.connector.serializer import deserialize_connector, serialize_connector
from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.sqlite.flattener import flatten
from elliot_core.tools.registry import ToolRegistry
from elliot_core.tools.validator import validate_tool_definition
from elliot_connector_runtime.cache import ConnectorCache
from elliot_connector_runtime.executor import ToolExecutor


CSV_DATA = (
    "id,name,category,price\n"
    "1,Widget A,gadgets,9.99\n"
    "2,Widget B,gadgets,19.99\n"
    "3,Donut,food,1.49\n"
)

TOOL_DEF = {
    "id": "list_products",
    "description": "Returns products filtered by category",
    "category": "READ",
    "source_ids": ["products"],
    "filter_groups": [
        {
            "logic": "AND",
            "conditions": [
                {
                    "field": "products.category",
                    "operator": "=",
                    "parameter_name": "category",
                }
            ],
        }
    ],
    "return_fields": [
        {"field": "products.id"},
        {"field": "products.name"},
        {"field": "products.price"},
    ],
    "limit": 50,
    "parameters": [
        {
            "name": "category",
            "type": "string",
            "required": False,
            "description": "Product category filter",
        }
    ],
}


@pytest.mark.asyncio
async def test_full_e2e_flow(tmp_path: Path) -> None:
    # ─ 1. Load CSV into in-memory SQLite ─────────────────────────────────
    engine = SQLiteEngine()
    rows = list(csv.DictReader(io.StringIO(CSV_DATA)))
    flat = flatten(rows, table_name="products")
    engine.load_result(flat)

    count = engine.query('SELECT COUNT(*) AS n FROM "products"')
    assert count[0]["n"] == 3

    # ─ 2. Validate tool definition ─────────────────────────────────────────
    tool = validate_tool_definition(TOOL_DEF)
    assert tool.id == "list_products"

    registry = ToolRegistry()
    registry.register(tool)

    # ─ 3. Build + serialize connector ──────────────────────────────────
    builder = ConnectorBuilder()
    builder.set_meta(name="Test Shop", version="1.0.0", slug="test-shop")
    connector_config = builder.build(sources=[], tools=[tool], skills=[])

    connector_json = serialize_connector(connector_config)
    connector_path = tmp_path / "test-shop.connector.json"
    connector_path.write_text(connector_json)

    # ─ 4. Deserialize + verify round-trip ──────────────────────────────
    loaded_config = deserialize_connector(connector_json)
    assert loaded_config.slug == "test-shop"
    assert len(loaded_config.tools) == 1
    assert loaded_config.tools[0].id == "list_products"

    # ─ 5. Execute via runtime ToolExecutor ─────────────────────────────
    executor = ToolExecutor(loaded_config, secrets={}, engine=engine)

    # Filter to gadgets only
    result = await executor.execute(loaded_config.tools[0], {"category": "gadgets"})
    assert len(result.rows) == 2
    assert {r["name"] for r in result.rows} == {"Widget A", "Widget B"}

    # No filter -> all rows
    result_all = await executor.execute(loaded_config.tools[0], {})
    assert len(result_all.rows) == 3

    # ─ 6. Verify ConnectorCache can load the exported file ────────────────
    cache = ConnectorCache(ttl_seconds=0)
    cached = cache.get(connector_path)
    assert cached.slug == "test-shop"
```

## Done When
- [ ] All 6 steps pass
- [ ] Test runs without any external service
- [ ] Full flow completes in < 10 seconds
- [ ] `pytest packages/connector-runtime/tests/integration/test_e2e_flow.py -v` exits 0
