# Elliot — AI Connector Platform

> Turn any REST API or database into MCP tools that AI agents can call directly — without rewriting your product.

Elliot wraps your existing APIs, databases, and files into a **Connector**: a versioned, locally-runnable MCP server. Write one `.connector.json` file describing your sources and the SQL queries you want to expose as tools. Elliot handles fetching, in-memory SQL, auth, audit logging, and the MCP protocol.

---

## How It Works

```
1. Write a .connector.json
   └─ describe your REST endpoints, DB tables, and the SQL tools you want

2. Start elliot-mcp-plugin (:3000)
   └─ Claude Code connects via MCP StreamableHTTP
   └─ Claude discovers your tools and calls them naturally

3. Start elliot-connector-runtime (:3001)
   └─ Fetches live data from your API / DB on each tool call
   └─ Runs the tool’s SQL query in ephemeral in-memory SQLite
   └─ Returns structured rows + writes to audit log

4. Open Elliot Studio (:5173)
   └─ Browse sources, run tools manually, inspect the audit log
```

---

## Repository Structure

```
elliot/
├── packages/
│   ├── core/                  elliot-core          Python library (types, SQLite engine, errors)
│   ├── mcp-plugin/            elliot-mcp-plugin    MCP + FastAPI server  :3000
│   ├── connector-runtime/     elliot-connector-runtime  Runtime MCP server  :3001
│   └── studio/                elliot-studio        React + Vite dashboard  :5173
├── docs/                      Architecture diagrams, data-flow, test plan
├── tasks/                     59 ordered implementation tasks (7 epic folders)
├── Procfile                   Start all services with honcho / foreman
├── pyproject.toml             uv workspace root
└── package.json               pnpm workspace root (studio only)
```

---

## Tech Stack

| Layer | Language | Key Libraries |
|---|---|---|
| Shared types & engine | Python 3.12 | `pydantic`, `sqlite3` (stdlib), `httpx`, `jmespath` |
| MCP plugin server | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog` |
| Connector runtime | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `respx` (tests) |
| Studio UI | TypeScript | React 18, Vite, Tailwind CSS, shadcn/ui, Zustand, `@modelcontextprotocol/sdk` |
| Monorepo tooling | Python → `uv` · TypeScript → `pnpm` | |

---

## Services & Ports

| Service | Port | Command |
|---|---|---|
| `elliot-mcp-plugin` | **3000** | `uv run uvicorn elliot_mcp_plugin.server:app --port 3000 --reload` |
| `elliot-connector-runtime` | **3001** | `uv run uvicorn elliot_connector_runtime.server:app --port 3001 --reload` |
| `elliot-studio` | **5173** | `pnpm --filter elliot-studio dev` |

Or start all three at once:

```bash
honcho start   # reads Procfile
```

---

## Quick Start

### Prerequisites

```bash
# Python 3.12+ with uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Node 20+ with pnpm
npm install -g pnpm
```

### Install

```bash
git clone https://github.com/elibarak12/elliot.git
cd elliot

# Python packages (all three services + core)
uv sync

# Studio UI
pnpm install
```

### Run

```bash
# Option A — all services together
honcho start

# Option B — individually
ELLIOT_CONNECTORS_DIR=./connectors \
  uv run uvicorn elliot_mcp_plugin.server:app \
  --port 3000 --reload --app-dir packages/mcp-plugin/src

ELLIOT_CONNECTOR=./my-api.connector.json \
  uv run uvicorn elliot_connector_runtime.server:app \
  --port 3001 --reload --app-dir packages/connector-runtime/src

pnpm --filter elliot-studio dev
```

### Connect Claude Code

Add to `~/.claude/claude_desktop_config.json` (or `.mcp.json` in your project root):

```json
{
  "mcpServers": {
    "elliot": {
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

---

## Connector File Example

```json
{
  "name": "Pet Store API",
  "slug": "petstore",
  "version": "1.0.0",
  "sources": [
    {
      "id": "animals",
      "name": "Animals endpoint",
      "type": "rest",
      "url": "https://api.example.com/animals",
      "data_path": "items",
      "auth": { "type": "api_key", "secret_key": "PETSTORE_API_KEY" }
    }
  ],
  "tools": [
    {
      "id": "list_animals",
      "name": "List animals",
      "description": "Return all animals, optionally filtered by species",
      "category": "READ",
      "sql": "SELECT * FROM animals WHERE (:species IS NULL OR species = :species)",
      "parameters": [
        { "name": "species", "type": "string", "description": "Filter by species", "required": false }
      ]
    }
  ],
  "skills": []
}
```

---

## Testing

```bash
# Python — all packages
uv run pytest packages/ -v

# With coverage (individual gates)
uv run pytest packages/core/tests/              --cov=elliot_core              --cov-fail-under=95
uv run pytest packages/connector-runtime/tests/ --cov=elliot_connector_runtime --cov-fail-under=85
uv run pytest packages/mcp-plugin/tests/        --cov=elliot_mcp_plugin        --cov-fail-under=80

# Studio
cd packages/studio && npx vitest run --coverage
```

---

## Documentation

### Current (reflects Python implementation)

| Doc | Description |
|---|---|
| [docs/architecture.md](docs/architecture.md) | System diagram, package deps, directory tree, Pydantic class diagram |
| [docs/data-flow.md](docs/data-flow.md) | Sequence diagrams: tool call, cache load, Studio flow, error handling |
| [docs/product-overview.md](docs/product-overview.md) | User journey, Studio pages, component tree, state shape, design decisions |
| [docs/test-plan.md](docs/test-plan.md) | Test pyramid, per-package coverage gates, CI pipeline, mock strategy |
| [tasks/README.md](tasks/README.md) | 59 ordered implementation tasks across 7 epic folders |

### Legacy (original TypeScript design — domain concepts still valid)

| Doc | Description |
|---|---|
| [docs/CORE_CONCEPTS.md](docs/CORE_CONCEPTS.md) | Products, Endpoints, Tools, Skills, Prompts, Connectors explained |
| [docs/PRODUCT_SPECIFICATION.md](docs/PRODUCT_SPECIFICATION.md) | All-phases product spec and user stories |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Original TypeScript architecture (see migration notice inside) |
| [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md) | TypeScript dev guide + Python quick start added at top |
| [docs/MCP_SSE_TRANSPORT.md](docs/MCP_SSE_TRANSPORT.md) | MCP transport details (StreamableHTTP, SSE) |
| [docs/STUDIO_MCP_TRANSPORT.md](docs/STUDIO_MCP_TRANSPORT.md) | Studio ↔ MCP plugin transport wiring |

---

## License

MIT
