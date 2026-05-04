# Elliot — AI AX (Agent Experience) Platform

> **AX** is to agents what UX is to users and DX is to developers. Elliot is the interface layer that makes your product feel native to AI agents — design, validate, deploy, and observe agent-ready tools built around your existing APIs, databases, and files.

Turn your existing product into an agentic-native product. Elliot wraps your data sources in MCP tools agents can call efficiently — with minimum tokens, clean error recovery, and full observability of every session.

---

## The Problem

Connecting an API to Claude is easy. Making it work *well* with agents is not. Agents fail when:
- Tool descriptions are vague → wrong tool called
- Results are too large → context window fills up
- Errors are unstructured → agent can’t recover
- No observability → you don’t know it’s broken

Elliot makes these problems visible and fixable.

---

## How It Works

```
1. Connect your data sources
   └ REST APIs, PostgreSQL, MySQL, CSV / JSON files — all in one connector

2. Build tools (no SQL required)
   └ Agent or user defines: name, description, parameters, filters, return fields
   └ Elliot generates the safe parameterized query or API call internally
   └ OR: let an AI agent build the connector for you via agentic builder tools

3. Lint for agent-readiness
   └ elliot lint my-domain.connector.json
   └ catches vague descriptions, unbounded results, unclear parameter names

4. Write and run eval cases
   └ elliot eval my-domain.eval.yaml → pass/fail + token estimate per tool

5. Deploy and connect agents
   └ elliot-mcp-plugin (:3000) — Claude Code / any MCP client connects here
   └ elliot-connector-runtime (:3001) — fetches live data, logs sessions
   └ elliot-studio (:5173) — observe sessions, run tools, track quality

6. Observe and improve
   └ Studio Agent Console: every agent connection, every tool call, params, tokens, errors
   └ Elliot flags: “this tool returned 1,200 tokens — consider adding a filter”
   └ Edit in the visual Connector Editor — no JSON editing required
```

---

## Getting Started

```bash
# Prerequisites: uv (Python), pnpm (Node)
curl -LsSf https://astral.sh/uv/install.sh | sh
npm install -g pnpm

# Install
git clone https://github.com/elibarak12/elliot.git && cd elliot
uv sync && pnpm install

# Copy env vars
cp .env.example .env

# Start all services
honcho start

# Check status
elliot status

# Scaffold your first connector from a template
elliot init --template rest-api-key my-api.connector.json

# Or let an agent build it for you
# Connect Claude Code to http://localhost:3000/mcp
# Then: "I have an API at https://api.myapp.com — help me build a connector"

# Lint and test
elliot lint my-api.connector.json
elliot eval my-api.eval.yaml
```

Connect Claude Code — `.mcp.json` is already in the repo root:
```json
{ "mcpServers": { "elliot": { "url": "http://localhost:3000/mcp" } } }
```

---

## Repository Structure

```
elliot/
├── packages/
│   ├── core/                  elliot-core          types, query builder, linter, eval runner
│   ├── mcp-plugin/            elliot-mcp-plugin    MCP + FastAPI :3000 + agentic builder tools
│   ├── connector-runtime/     elliot-connector-runtime  runtime :3001 + session tracker
│   └── studio/                elliot-studio        React + Vite :5173
├── connectors/            your connector.json files
├── templates/             starter connectors (elliot init --list)
├── docs/
│   ├── agentic-product-design.md  ← start here
│   ├── architecture.md
│   ├── user-stories.md
│   └── test-plan.md
├── tasks/                 79 ordered implementation tasks
├── CLAUDE.md              AI agent instructions for this repo
├── Procfile               honcho dev runner
├── docker-compose.yml     production deployment
└── .env.example           all env vars documented
```

---

## Tech Stack

| Layer | Language | Key Libraries |
|---|---|---|
| Core library | Python 3.12 | `pydantic`, `sqlite3`, `httpx`, `sqlalchemy` |
| MCP plugin | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog` |
| Connector runtime | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `slowapi`, `pymysql` |
| Studio UI | TypeScript | React 18, Vite, Tailwind, shadcn/ui, Zustand |
| Package managers | Python → `uv` · TypeScript → `pnpm` | |

---

## Key Ports

| Service | Port | Purpose |
|---|---|---|
| `elliot-mcp-plugin` | 3000 | MCP endpoint for agents + agentic builder tools |
| `elliot-connector-runtime` | 3001 | Tool execution, session tracking, observation store |
| `elliot-studio` | 5173 | Visual dashboard — sessions, tools, metrics, editor |

---

## Documentation

| Doc | Description |
|---|---|
| [docs/agentic-product-design.md](docs/agentic-product-design.md) | **Start here.** What AX means, the 5 principles, feedback loop, connector model |
| [docs/user-stories.md](docs/user-stories.md) | Three personas, full journeys, what “good enough” looks like |
| [docs/architecture.md](docs/architecture.md) | System diagram, package deps, directory tree, Pydantic models |
| [docs/test-plan.md](docs/test-plan.md) | Test pyramid, coverage gates, CI pipeline |
| [tasks/README.md](tasks/README.md) | 79 ordered implementation tasks with build phase sequence |

---

## License

MIT
