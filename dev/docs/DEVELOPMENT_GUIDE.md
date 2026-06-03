> ⚠️ **Migration notice** — the backend has moved from TypeScript to **Python 3.12**.
> The Python quick start is at the top of this file. The TypeScript section below covers the Studio UI (still valid) and the original TS backend (historical reference only).

---

# Python Quick Start (current stack)

## Prerequisites

```bash
# Python 3.12+ with uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Node 20+ with pnpm (for Studio only)
npm install -g pnpm
```

## Install all packages

```bash
git clone https://github.com/elibarak12/elliot.git
cd elliot
uv sync          # installs elliot-core, elliot-mcp-plugin, elliot-connector-runtime
pnpm install     # installs elliot-studio
```

## Run the services

```bash
# All at once
honcho start

# Individually
ELLIOT_CONNECTORS_DIR=./connectors \
  uv run uvicorn elliot_mcp_plugin.server:app \
  --port 3000 --reload --app-dir packages/mcp-plugin/src

ELLIOT_CONNECTOR=./my-api.connector.json \
  uv run uvicorn elliot_connector_runtime.server:app \
  --port 3001 --reload --app-dir packages/connector-runtime/src

pnpm --filter elliot-studio dev   # :5173
```

## Run tests

```bash
# All Python tests
uv run pytest packages/ -v

# With coverage gates
uv run pytest packages/core/tests/              --cov=elliot_core              --cov-fail-under=95
uv run pytest packages/connector-runtime/tests/ --cov=elliot_connector_runtime --cov-fail-under=85
uv run pytest packages/mcp-plugin/tests/        --cov=elliot_mcp_plugin        --cov-fail-under=80

# Studio
cd packages/studio && npx vitest run --coverage
```

## Environment variables

| Variable | Service | Default | Purpose |
|---|---|---|---|
| `ELLIOT_CONNECTORS_DIR` | plugin | `.` | Directory to scan for `*.connector.json` files |
| `ELLIOT_CONNECTOR` | runtime | `connector.json` | Path to a single connector file to serve |
| `ELLIOT_AUDIT_LOG` | runtime | `.elliot/audit.ndjson` | Audit log output path |
| `LOG_LEVEL` | both | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

## Connect to Claude Code

Add to `.mcp.json` in your project root (already present in this repo):

```json
{
  "mcpServers": {
    "elliot": { "url": "http://localhost:3000/mcp/" }
  }
}
```

---

> The rest of this file covers the original TypeScript development guide (Studio UI setup remains valid; backend TypeScript content is historical).

---
