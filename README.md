# Elliot — AI AX (Agent Experience) Platform

> **AX** is to agents what UX is to users and DX is to developers. Elliot is the interface layer that makes your product feel native to AI agents — design, validate, deploy, and observe agent-ready tools built around your existing APIs, databases, and files.

Turn your existing product into an agentic-native product. Elliot wraps your data sources in MCP tools agents can call efficiently — with minimum tokens, clean error recovery, and full observability of every session.

---

## The Problem

Connecting an API to Claude is easy. Making it work *well* with agents is not. Agents fail when:
- Tool descriptions are vague → wrong tool called
- Results are too large → context window fills up
- Errors are unstructured → agent can't recover
- No observability → you don't know it's broken

Elliot makes these problems visible and fixable.

---

## How It Works

```
1. Connect your data sources
   └ REST APIs, PostgreSQL, MySQL, CSV / JSON files — all in one connector

2. Build tools (no SQL required)
   └ Define: name, description, parameters, filter conditions, return fields
   └ Elliot generates safe parameterized queries internally
   └ OR: let an AI agent build the connector for you via the agentic builder

3. Lint for agent-readiness
   └ elliot lint my-domain.connector.json

4. Write and run eval cases
   └ elliot eval my-domain.eval.yaml → pass/fail + token estimate

5. Deploy and connect agents
   └ elliot-mcp-plugin (:3000) — Claude Code / any MCP client
   └ elliot-connector-runtime (:3001) — live data, session logs
   └ elliot-studio (:5173) — observe, run, edit
```

---

## Getting Started

```bash
# Prerequisites: uv (Python 3.13), pnpm (Node 22)
curl -LsSf https://astral.sh/uv/install.sh | sh
npm install -g pnpm

# Clone and install
git clone https://github.com/elibarak12/elliot.git && cd elliot
make setup

# Copy env vars
cp .env.example .env

# Start all services
honcho start          # or: make dev

# Check everything is running
elliot status

# Scaffold your first connector
elliot init --template rest-api-key my-api.connector.json

# Or let an agent build it for you:
# 1. Connect Claude Code to http://localhost:3000/mcp  (.mcp.json already wired)
# 2. Ask: "I have an API at https://api.myapp.com — help me build a connector"

# Lint + eval
elliot lint my-api.connector.json
elliot eval my-api.eval.yaml
```

---

## Repository Structure

```
elliot/
├── packages/
│   ├── core/              elliot-core          types, query builder, linter, eval
│   ├── mcp-plugin/        elliot-mcp-plugin    MCP + FastAPI :3000
│   ├── connector-runtime/ elliot-connector-runtime  runtime :3001 + session tracker
│   └── studio/            elliot-studio        React 19 + Vite :5173
├── connectors/        your .connector.json files
├── templates/         starter connectors
├── Procfile           honcho dev runner
├── docker-compose.yml production
└── .env.example       all env vars documented
```

---

## Tech Stack

| Layer | Language | Key Libraries |
|---|---|---|
| Core library | Python 3.13 | `pydantic`, `sqlite3`, `httpx`, `sqlalchemy` |
| MCP plugin | Python 3.13 | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog` |
| Connector runtime | Python 3.13 | `mcp` (FastMCP), `fastapi`, `uvicorn`, `slowapi`, `pymysql` |
| Studio UI | TypeScript | React 19, Vite, shadcn/ui, TanStack Router v1 / Query v5 / Table v8, Zustand v5 |
| Package managers | `uv` (Python) · `pnpm` (Node 22) | |

---

## Key Ports

| Service | Port | Purpose |
|---|---|---|
| `elliot-mcp-plugin` | 3000 | MCP endpoint for agents + agentic builder tools |
| `elliot-connector-runtime` | 3001 | Tool execution, session tracking, observation store |
| `elliot-studio` | 5173 | Visual dashboard — sessions, tools, metrics, editor |

---

## License

MIT
