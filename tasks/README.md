# Elliot — Task List

75 ordered tasks across 4 sprints, organized into 9 epic folders.

**Backend**: Python 3.12 + uv workspaces 
**Frontend**: TypeScript + React + Vite + shadcn/ui

## Folder Structure

| Folder | Sprint | Tasks | Focus | Est. Hours |
|--------|--------|-------|-------|------------|
| [01-monorepo-setup](01-monorepo-setup/) | 1 | 001–004 | Workspace, config, tooling | 4–5h |
| [02-core-library](02-core-library/) | 1 | 005–021 | `elliot-core` Python library | 36–43h |
| [03-mcp-plugin](03-mcp-plugin/) | 2 | 022–032 | `elliot-mcp-plugin` (FastMCP + FastAPI :3000) | 28–34h |
| [04-connector-runtime](04-connector-runtime/) | 3 | 033–037 | `elliot-connector-runtime` (FastAPI :3001) | 20–24h |
| [05-studio-ui](05-studio-ui/) | 4 | 038–048 | Studio React app (TypeScript :5173) | 30–36h |
| [06-eval-and-polish](06-eval-and-polish/) | 4 | 049–056 | Eval, quality, CI | 18–22h |
| [07-dx-and-observability](07-dx-and-observability/) | 4 | 057–059 | Logging, error middleware, test plan | 6–8h |
| [08-agent-observability](08-agent-observability/) | 4 | 060–067 | Session tracking, linter, eval, agent console, token metrics, secrets, local DB | 31–39h |
| [09-platform-and-builder](09-platform-and-builder/) | 4 | 068–075 | Auth, deployment, agentic builder, connector editor, multi-connector, rate limiting, templates | 41–55h |

**Total**: ~214–266 hours

## Tech Stack

| Layer | Language | Key Libraries |
|-------|----------|---------------|
| Core library | Python | `pydantic`, `httpx`, `jmespath`, `sqlite3` (stdlib) |
| MCP Plugin | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog` |
| Connector Runtime | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog`, `sqlalchemy`, `pymysql` |
| Studio UI | TypeScript | React, Vite, shadcn/ui, `@modelcontextprotocol/sdk` |

## Epic Summaries

### [01 — Monorepo Setup](01-monorepo-setup/)
Initialize the uv + pnpm workspace, shared Python/TypeScript tooling configs (pytest, mypy, ruff, ESLint), and per-package stubs. Done when `uv sync` and `pnpm install` both succeed.

### [02 — Core Library](02-core-library/)
The `elliot-core` Python package: Pydantic types, JSON flattener, SQLite engine, API/file/DB source fetchers, tool validator, tool registry, tool executor, skill runner, connector builder/serializer. Done when `uv run pytest` hits ≥ 95% coverage.

### [03 — MCP Plugin](03-mcp-plugin/)
The `elliot-mcp-plugin` package: `ElliotSession` singleton, `FastMCP` server factory on port 3000, all MCP tool groups (source, SQL, tool, skill, context, connector, studio meta-tools), FastAPI HTTP server, and install script for Claude Code.

### [04 — Connector Runtime](04-connector-runtime/)
The `elliot-connector-runtime` package on port 3001: loads a `.connector.json`, caches it with TTL + mtime, executes tools against live REST/DB sources via ephemeral SQLite, serves them as MCP, includes OpenAI-compatible `/v1/chat/completions` endpoint and audit log.

### [05 — Studio UI](05-studio-ui/)
The `elliot-studio` TypeScript React app: Vite + shadcn/ui, React Router app shell, MCP client (StreamableHTTPClientTransport), Zustand store, all pages (Dashboard, Tools, Skills, Playground, Metrics/Audit).

### [06 — Eval & Polish](06-eval-and-polish/)
Evaluation runner + quality analyzer in `elliot-core`, eval page UI, error class hierarchy, error handling audit, empty states, end-to-end integration test, GitHub Actions CI workflow.

### [07 — DX & Observability](07-dx-and-observability/)
Structured JSON logging with `structlog` for both Python services (task 057), FastAPI global error middleware mapping `ElliotError` subclasses to HTTP status codes (task 058), and the full test strategy document covering pyramid, mocking rules, CI ordering, and coverage gates per package (task 059).

### [08 — Agent Observability](08-agent-observability/)
The layer that turns Elliot into a true agentic-product platform. Upgrades the flat audit log to a full **SessionTracker** (task 060), adds a **Tool Quality Linter** `elliot lint` (task 061), YAML **Eval Test Case** schema (task 062), async **Eval Runner** `elliot eval` (task 063), **Studio Agent Console** (task 064), **Token Efficiency Metrics** (task 065), **Secrets Management** with `{{ env:VAR }}` placeholders (task 066), and a **Local SQLite/MySQL Observation Store** via SQLAlchemy (task 067).

### [09 — Platform & Agentic Builder](09-platform-and-builder/)
The layer that makes Elliot itself an agentic product. **API Key Auth** on all endpoints (task 068). **Docker Compose + production Dockerfiles** so the whole stack ships in one command (task 069). **OpenAPI Spec Analyzer** that parses any OpenAPI 3.x spec and returns a proposed connector draft with descriptions, parameters, and token risk flags (task 070). **Agentic Connector Builder MCP tools** — a set of tools exposed on Elliot's own plugin that let an AI agent build a connector interactively with the user: analyze spec → filter tools → refine descriptions → lint → save — no JSON editing required (task 071). **Connector Editor UI** in Studio — a visual form editor for sources and tools with a live lint panel (task 072). **Multi-connector runtime directory mode** so one process serves all connectors namespaced by slug (task 073). **Rate limiting** via `slowapi` to protect upstream APIs from runaway agents (task 074). **Connector starter templates** with `elliot init --template <name>` CLI (task 075).
