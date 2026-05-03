# Task 059 — Test Plan & Strategy

## Goal
Define the full testing strategy for the Elliot monorepo: what to test at each layer, how tests are organized, what gets mocked vs real, CI ordering, and per-package coverage gates.

## Test pyramid

```
        ┌─────────────────────┐
        │     E2E / smoke     │  1–2 tests, real processes
        ├─────────────────────┤
        │    Integration      │  TestClient + respx mocks
        ├─────────────────────┤
        │      Unit           │  pure logic, no I/O
        └─────────────────────┘
```

## Per-package test scope

### `packages/core` — `elliot-core`

| Module | Test type | Key scenarios |
|---|---|---|
| `types.py` | Unit | Pydantic validation: missing fields, wrong types, extra fields ignored |
| `sqlite_engine.py` | Unit | ingest flat list, ingest nested (flattened), query with params, empty result |
| `errors.py` | Unit | `ElliotError` subclasses carry correct `code`, str representation |
| `json_flattener.py` | Unit | nested dict, list of dicts, deeply nested, empty input |

Coverage gate: **95%**

### `packages/mcp-plugin` — `elliot-mcp-plugin`

| Module | Test type | Key scenarios |
|---|---|---|
| `session.py` | Integration | session created, tool list returned, tool called |
| `tools/source_tools.py` | Unit | REST source tool builds correct MCP tool descriptor |
| `tools/sql_tools.py` | Unit | SQL tool builds correct MCP tool descriptor |
| `server.py` | Integration | `/health` → 200, `/mcp` mount responds |
| Error middleware | Integration | `ElliotError` → correct HTTP status + JSON envelope |

Coverage gate: **80%** (MCP transport layer excluded)

### `packages/connector-runtime` — `elliot-connector-runtime`

| Module | Test type | Key scenarios |
|---|---|---|
| `loader.py` | Unit | valid file, missing file, bad JSON, schema fail, wrong suffix |
| `cache.py` | Unit | cache hit, mtime invalidation, TTL expiry, thread safety |
| `executor.py` | Integration | REST source (respx mock), empty result, URL interpolation, data_path extraction |
| `audit.py` | Unit | record + tail, tail empty, tail limit, concurrent writes |
| `server.py` | Integration | `/health`, `/v1/audit`, OpenAI tools schema |
| Error middleware | Integration | typed errors → correct HTTP codes |

Coverage gate: **85%** (psycopg2 DB path excluded)

### `packages/studio` — `elliot-studio` (TypeScript/React)

| Area | Test type | Tool | Key scenarios |
|---|---|---|---|
| Zustand store | Unit | Vitest | initial state, set connector, clear |
| MCP client | Unit | Vitest + msw | list tools, call tool, error response |
| `SourcesPanel` | Component | Vitest + RTL | renders sources, empty state |
| `ToolsPage` | Component | Vitest + RTL | renders tools, runs tool, shows result |
| `Playground` | Component | Vitest + RTL | parameter form, submit, error display |

Coverage gate: **70%** (UI components can be lower)

## What to mock vs real

| Dependency | Strategy |
|---|---|
| REST APIs (httpx) | `respx.mock` — never hit real endpoints in CI |
| PostgreSQL / MySQL | Skip with `pytest.mark.skip` unless `TEST_DB_DSN` env var set |
| MCP transport (StreamableHTTP) | `TestClient` in-process — no real server |
| File system | `tmp_path` pytest fixture — isolated temp dirs |
| Time (`time.monotonic`, `time.time`) | `monkeypatch` only when testing TTL/expiry |
| External APIs in Studio | `msw` (Mock Service Worker) in Vitest |

## Fixture strategy

```python
# conftest.py (connector-runtime tests)
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from elliot_connector_runtime.server import create_app

MINIMAL_CONNECTOR = { ... }  # see task 037

@pytest.fixture(scope="session")
def connector_file(tmp_path_factory):
    p = tmp_path_factory.mktemp("connectors") / "test.connector.json"
    p.write_text(json.dumps(MINIMAL_CONNECTOR))
    return p

@pytest.fixture(scope="session")
def app(connector_file):
    return create_app(connector_path=str(connector_file), secrets={})

@pytest.fixture(scope="session")
def client(app):
    return TestClient(app)
```

Use `scope="session"` for the app/client to avoid rebuilding per test.

## CI test ordering

```yaml
# .github/workflows/ci.yml test jobs (run in parallel where possible)
jobs:
  test-core:          # fastest — pure Python, no I/O
  test-mcp-plugin:   # depends on core build
  test-runtime:      # depends on core build
  test-studio:       # independent — TypeScript only
  test-e2e:          # depends on all above passing
```

## E2E smoke test

One pytest test in `tests/e2e/test_smoke.py` at the repo root:

```python
import subprocess, time, httpx, pytest

@pytest.mark.e2e
def test_runtime_serves_connector(tmp_path):
    # Write a minimal connector file
    # Start uvicorn as a subprocess
    # Wait for /health to return 200
    # Call /v1/audit, assert list returned
    # Terminate process
    ...
```

Run only in CI after all unit/integration jobs pass:

```bash
uv run pytest tests/e2e/ -m e2e -v
```

## Coverage commands

```bash
# Python (per package)
uv run pytest packages/core/tests/ --cov=elliot_core --cov-fail-under=95
uv run pytest packages/connector-runtime/tests/ --cov=elliot_connector_runtime --cov-fail-under=85
uv run pytest packages/mcp-plugin/tests/ --cov=elliot_mcp_plugin --cov-fail-under=80

# TypeScript
cd packages/studio && npx vitest run --coverage --coverage.thresholds.lines=70
```

## Dev dependencies to add

```toml
# All Python packages
[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "respx>=0.21",
    "httpx>=0.27",
]
```

```json
// packages/studio/package.json
"devDependencies": {
  "@vitest/coverage-v8": "^1.0",
  "@testing-library/react": "^15.0",
  "@testing-library/user-event": "^14.0",
  "msw": "^2.0"
}
```
