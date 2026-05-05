# Elliot — Test Plan & Quality Strategy

## Test Pyramid

- **Unit** (~80 tests): Pure functions, no I/O — Pydantic validation, SQL extraction, URL interpolation, JSON flattener, cache TTL logic
- **Integration** (~40 tests): FastAPI TestClient in-process, respx mocks for HTTP, tmp_path for file system
- **E2E / Smoke** (2–3 tests): Real uvicorn subprocess, real connector.json

## Per-Package Coverage Gates

| Package | Gate | Excludes |
|---|---|---|
| `elliot-core` | **95%** | — |
| `elliot-connector-runtime` | **85%** | `_query_postgres` (needs real DB) |
| `elliot-mcp-plugin` | **80%** | MCP transport internals |
| `elliot-studio` | **70% lines** | Generated code, `main.tsx` |

## Running Tests Locally

```bash
uv run pytest packages/core/tests/             --cov=elliot_core              --cov-fail-under=95  -v
uv run pytest packages/connector-runtime/tests/ --cov=elliot_connector_runtime --cov-fail-under=85  -v
uv run pytest packages/mcp-plugin/tests/        --cov=elliot_mcp_plugin        --cov-fail-under=80  -v

# Studio tests
cd packages/studio && npx vitest run --coverage
```
