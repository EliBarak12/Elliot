# Elliot — AI Connector Platform

> Turn your existing product into an agentic-native product: design tools that AI agents can use efficiently, observe how they actually use them, and know when the answers are good enough.

Elliot wraps your APIs and databases in MCP tools — but the real job is making those tools *agent-ready*: correct descriptions, right-sized results, structured errors, and a feedback loop so you can see exactly how agents use your product and improve it.

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
1. Write a .connector.json
   └ describe sources (REST / PostgreSQL) and tools (named SQL queries)

2. Run the quality linter
   └ catches vague descriptions, unbounded SELECTs, unclear parameter names

3. Write eval test cases (.eval.yaml)
   └ "call list_animals with species=dog, expect ≥1 row, all rows have species=dog"
   └ run: uv run elliot eval pets.eval.yaml → pass/fail report

4. Start the services
   └ elliot-mcp-plugin (:3000) — Claude Code connects here via MCP
   └ elliot-connector-runtime (:3001) — fetches live data, runs SQL, logs sessions
   └ elliot-studio (:5173) — observe agent sessions, run tools manually, track quality

5. Observe real agent sessions in Studio Agent Console
   └ see every tool call, params, result size, token cost, errors
   └ Elliot flags: "this tool returned 1,200 tokens — consider adding LIMIT"

6. Improve and re-eval
   └ connector.json → lint → eval → deploy → observe → improve
```

---

## Repository Structure

```
elliot/
├── packages/
│   ├── core/                  elliot-core          types, SQLite engine, linter, eval runner
│   ├── mcp-plugin/            elliot-mcp-plugin    MCP + FastAPI :3000
│   ├── connector-runtime/     elliot-connector-runtime  runtime :3001 + session tracker
│   └── studio/                elliot-studio        React + Vite :5173
├── docs/
│   ├── agentic-product-design.md  ← start here: what agentic-native means
│   ├── architecture.md
│   ├── data-flow.md
│   ├── product-overview.md
│   ├── test-plan.md
│   └── user-stories.md
├── tasks/                     59 + 6 = 65 ordered implementation tasks
├── pyproject.toml
└── package.json
```

---

## Tech Stack

| Layer | Language | Key Libraries |
|---|---|---|
| Core library | Python 3.12 | `pydantic`, `sqlite3`, `httpx`, `jmespath` |
| MCP plugin server | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog` |
| Connector runtime | Python | `mcp` (FastMCP), `fastapi`, `uvicorn` |
| Studio UI | TypeScript | React 18, Vite, Tailwind, shadcn/ui, Zustand |
| Package managers | Python → `uv` · TypeScript → `pnpm` | |

---

## Quick Start

```bash
# Prerequisites: uv (Python), pnpm (Node)
curl -LsSf https://astral.sh/uv/install.sh | sh
npm install -g pnpm

# Install
git clone https://github.com/elibarak12/elliot.git && cd elliot
uv sync && pnpm install

# Start all services
honcho start

# Lint your connector
uv run elliot lint my-api.connector.json

# Run eval cases
uv run elliot eval my-api.eval.yaml
```

Connect Claude Code — `.mcp.json` is already in the repo root:
```json
{ "mcpServers": { "elliot": { "url": "http://localhost:3000/mcp" } } }
```

---

## Documentation

| Doc | Description |
|---|---|
| [docs/agentic-product-design.md](docs/agentic-product-design.md) | **Start here.** The 5 principles of agent-ready tools, the feedback loop, linter output, eval format, session console |
| [docs/user-stories.md](docs/user-stories.md) | Three personas, full journeys, what “good enough” looks like |
| [docs/architecture.md](docs/architecture.md) | System diagram, package deps, directory tree, Pydantic models |
| [docs/data-flow.md](docs/data-flow.md) | Sequence diagrams: tool call, cache, Studio, error handling |
| [docs/product-overview.md](docs/product-overview.md) | Studio pages, component tree, state shape |
| [docs/test-plan.md](docs/test-plan.md) | Test pyramid, coverage gates, CI pipeline, mocking strategy |
| [tasks/README.md](tasks/README.md) | 65 ordered implementation tasks across 8 epic folders |
| [docs/CORE_CONCEPTS.md](docs/CORE_CONCEPTS.md) | Domain model: Sources, Tools, Skills, Auth, Connectors |
| [docs/PRODUCT_SPECIFICATION.md](docs/PRODUCT_SPECIFICATION.md) | All-phases spec, user stories, KPIs |

---

## License

MIT
