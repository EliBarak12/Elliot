# Elliot — Task List

81 ordered tasks across 10 epics. The **Folder Structure** table is for navigation. The **Build Order** is the sequence to implement them.

**Backend**: Python 3.13 + uv workspaces 
**Frontend**: TypeScript + React 19 + Vite + shadcn/ui + TanStack

---

## Folder Structure (navigation)

| Folder | Tasks | Focus |
|--------|-------|-------|
| [01-monorepo-setup](01-monorepo-setup/) | 001–004 | Workspace, config, tooling |
| [02-core-library](02-core-library/) | 005–021 | `elliot-core` Python library |
| [03-mcp-plugin](03-mcp-plugin/) | 022–032 | `elliot-mcp-plugin` (FastMCP + FastAPI :3000) |
| [04-connector-runtime](04-connector-runtime/) | 033–037 | `elliot-connector-runtime` (FastAPI :3001) |
| [05-studio-ui](05-studio-ui/) | 038–048 | Studio React app (TypeScript :5173) |
| [06-eval-and-polish](06-eval-and-polish/) | 049–056 | Eval, quality, CI |
| [07-dx-and-observability](07-dx-and-observability/) | 057–059 | Logging, error middleware, test plan |
| [08-agent-observability](08-agent-observability/) | 060–067 | Session tracking, linter, eval, agent console, token metrics, secrets, local DB |
| [09-platform-and-builder](09-platform-and-builder/) | 068–079 | Auth, deployment, agentic builder, editor, multi-connector, rate limiting, templates, status CLI, schema introspection, health check |
| [10-ax-legibility](10-ax-legibility/) | 080–081 | Before/after AX benchmark, preloaded demo connector + `/welcome` (per `dev/docs/AX_STRATEGY.md`) |

**Total**: ~230–285 hours

---

## Build Order

### Phase 1 — Foundation

| # | Task | What it unlocks |
|---|------|----------------|
| 1 | 001 | Monorepo workspace |
| 2 | 002 | Python tooling (ruff, mypy, pytest) |
| 3 | 003 | TypeScript tooling (ESLint, Vitest) |
| 4 | 004 | Package stubs |
| 5 | 005 | Core type definitions — `ConnectorConfig`, `ToolDefinition` (filter/return model), `SourceConfig` |
| 6 | 052 | `ElliotError` hierarchy — used by every service |
| 7 | 057 | Structured logging (`structlog`) |
| 8 | 058 | Error middleware (`ElliotError` → HTTP status) |
| 9 | 068 | API key auth on all endpoints |
| 10 | 066 | Secrets management (`{{ env:VAR }}` in connector files) |

### Phase 2 — Core Library

| # | Task | What it unlocks |
|---|------|----------------|
| 11 | 006 | Column namer / type inferrer |
| 12 | 007 | JSON flattener |
| 13 | 008 | Flattener tests |
| 14 | 009 | SQLite engine (ingest + query) |
| 15 | 010 | SQL query validator |
| 16 | 011 | SQLite tests |
| 17 | 012 | REST API fetcher |
| 18 | 013 | File reader (CSV / JSON / JSONL) |
| 19 | 014 | DB connector (Postgres / MySQL) |
| 20 | 015 | Source tests |
| 21 | 016 | Tool validator |
| 22 | 017 | Tool registry |
| 23 | 018 | Tool executor + query builder (filter config → safe SQL; api_mapping → HTTP call) |
| 24 | 019 | Skill runner |
| 25 | 020 | Connector builder / serializer |
| 26 | 021 | Core public API (`__init__.py`) |

### Phase 3 — Connector Creation Tools

| # | Task | What it unlocks |
|---|------|----------------|
| 27 | 059 | Test plan strategy document |
| 28 | 075 | Connector starter templates (`elliot init --template`) |
| 29 | 070 | OpenAPI spec analyzer → `ProposedConnector` |
| 30 | 061 | Tool quality linter (`elliot lint`) |
| 31 | 062 | Eval test case YAML schema |

### Phase 4 — Runtime Services

| # | Task | What it unlocks |
|---|------|----------------|
| 32 | 033 | Runtime loader + cache (TTL + mtime) |
| 33 | 034 | Runtime executor (wraps core ToolExecutor) |
| 34 | 067 | Observation store (SQLite default / MySQL optional) |
| 35 | 060 | Agent session tracker (on top of observation store) |
| 36 | 035 | Runtime FastMCP server (:3001) |
| 37 | 036 | Runtime OpenAI endpoint + audit wired to store |
| 38 | 037 | Runtime tests |
| 39 | 073 | Multi-connector directory mode |
| 40 | 074 | Rate limiting (`slowapi`) |
| 41 | 078 | Health check (`GET /v1/health`) + source connection test |

### Phase 5 — MCP Plugin & Agentic Builder

| # | Task | What it unlocks |
|---|------|----------------|
| 42 | 022 | Plugin `ElliotSession` |
| 43 | 023 | Plugin FastMCP server factory (:3000) |
| 44 | 024 | Plugin source tools |
| 45 | 025 | Plugin SQL tools |
| 46 | 026 | Plugin skill tools |
| 47 | 027 | Plugin context tools |
| 48 | 028 | Plugin connector meta-tools |
| 49 | 029 | Plugin studio meta-tools |
| 50 | 030 | Plugin FastAPI HTTP server |
| 51 | 031 | Plugin install script for Claude Code |
| 52 | 032 | Plugin tests |
| 53 | 077 | DB schema introspection (builder tool: inspect columns before proposing fields) |
| 54 | 071 | Agentic connector builder MCP tools (agent builds connector interactively) |
| 55 | 076 | `elliot status` CLI |

### Phase 6 — Studio UI

| # | Task | What it unlocks |
|---|------|----------------|
| 56 | 038 | Studio Vite + shadcn/ui scaffold (React 19) |
| 57 | 039 | App shell (nav, layout, TanStack Router) |
| 58 | 040 | MCP client (`StreamableHTTPClientTransport`) |
| 59 | 041 | Zustand store (UI state) + TanStack Query setup (server state) |
| 60 | 042 | Dashboard / sources page |
| 61 | 043 | Tools page (TanStack Table) |
| 62 | 044 | Skills page |
| 63 | 045 | Meta-tools page |
| 64 | 046 | Playground |
| 65 | 047 | Metrics / audit page (TanStack Table) |
| 66 | 048 | Studio UI tests |
| 67 | 064 | Studio Agent Console (real-time session tree) |
| 68 | 065 | Token efficiency metrics |
| 69 | 072 | Connector editor UI (visual form, live lint panel) |

### Phase 7 — Quality Gates

| # | Task | What it unlocks |
|---|------|----------------|
| 70 | 063 | Eval runner CLI (`elliot eval`) |
| 71 | 049 | Eval runner in `elliot-core` |
| 72 | 050 | Quality analyzer |
| 73 | 051 | Eval page in Studio |
| 74 | 053 | Error handling audit |
| 75 | 054 | Studio empty states |

### Phase 8 — Ship

| # | Task | What it unlocks |
|---|------|----------------|
| 76 | 055 | E2E integration test (agent → plugin → runtime → DB) |
| 77 | 056 | CI workflow (GitHub Actions) |
| 78 | 069 | Docker Compose + production Dockerfiles |
| 79 | — | README onboarding section already in place |

---

## Tech Stack

| Layer | Language | Key Libraries |
|-------|----------|---------------|
| Core library | Python | `pydantic`, `httpx`, `sqlite3`, `sqlalchemy` |
| MCP Plugin | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog`, `slowapi` |
| Connector Runtime | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog`, `sqlalchemy`, `pymysql`, `asyncpg` |
| Studio UI | TypeScript | React 19, Vite, shadcn/ui, TanStack Router v1, TanStack Query v5, TanStack Table v8, Zustand v5, `@modelcontextprotocol/sdk` |

---

## Epic Summaries

### [01 — Monorepo Setup](01-monorepo-setup/)
Workspace, tooling configs, package stubs.

### [02 — Core Library](02-core-library/)
`elliot-core`: Pydantic types (filter/return tool model), SQLite engine, query builder (filter config → safe SQL), REST fetcher, file reader, DB connector, tool executor (handles both READ → SQL and WRITE → HTTP paths), skill runner, connector serializer. Target: ≥ 95% coverage.

### [03 — MCP Plugin](03-mcp-plugin/)
`elliot-mcp-plugin` on :3000: session, FastMCP server, all MCP tool groups, FastAPI HTTP layer, Claude Code install script.

### [04 — Connector Runtime](04-connector-runtime/)
`elliot-connector-runtime` on :3001: loader + cache, executor, FastMCP server, OpenAI endpoint, observation store, session tracker.

### [05 — Studio UI](05-studio-ui/)
`elliot-studio` React 19 app on :5173: TanStack Router for navigation, TanStack Query for server state, TanStack Table for data grids, Zustand for UI state, shadcn/ui components.

### [06 — Eval & Polish](06-eval-and-polish/)
Eval runner, quality analyzer, eval UI, error audit, empty states, E2E test, CI.

### [07 — DX & Observability](07-dx-and-observability/)
`structlog` logging, error middleware, test strategy.

### [08 — Agent Observability](08-agent-observability/)
Session tracker, tool linter, eval YAML schema, eval runner CLI, Studio Agent Console, token efficiency metrics, secrets management, SQLAlchemy observation store.

### [09 — Platform & Agentic Builder](09-platform-and-builder/)
API key auth, Docker Compose, OpenAPI analyzer, **agentic connector builder MCP tools** (agent defines tools using filter/return concepts — no SQL), **DB schema introspection** (agent sees columns before proposing fields), connector editor UI, multi-connector runtime, rate limiting, templates, `elliot status` CLI, health check + source connection test.
