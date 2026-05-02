# 028 — Plugin Source + SQL Integration Tests

**Sprint**: 2 | **Estimate**: 3h | **Depends on**: 025

## Objective
Test source and SQL tools by hitting the real MCP server with `httpx` (no mocks).

## Files to Create
- `packages/mcp-plugin/tests/integration/test_source_tools.py`
- `packages/mcp-plugin/tests/integration/test_sql_tools.py`
- `packages/mcp-plugin/tests/conftest.py`

## `conftest.py` — shared fixture
```python
import pytest
from elliot_mcp_plugin.session import ElliotSession
from elliot_mcp_plugin.server import create_elliot_server

@pytest.fixture
def session(tmp_path):
    return ElliotSession(cwd=str(tmp_path))

@pytest.fixture
def mcp(session):
    return create_elliot_server(session)
```

**Testing strategy**: call the tool functions directly (they are plain Python functions registered on FastMCP). Import the underlying function, call it, assert on the dict response.

```python
# test_source_tools.py
def test_discover_csv_source(mcp, session, tmp_path):
    # copy fixture CSV to tmp_path
    # call elliot_discover_source directly via session
    from elliot_mcp_plugin.tools.source_tools import _discover_source
    result = _discover_source(session, source_type="file", config={"path": str(csv)}, name="customers")
    assert "source_id" in result
    assert len(session.engine.get_table_names()) > 0

def test_list_sources(session): ...
def test_remove_source_drops_table(session): ...
```

## Done When
- [ ] All source tool tests pass without a running HTTP server
- [ ] All SQL tool tests pass
- [ ] `uv run pytest packages/mcp-plugin/tests/ -v` exits 0
