# Elliot — Task List

59 ordered tasks across 4 sprints, organized into 7 epic folders.

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

**Total**: ~142–172 hours

## Tech Stack

| Layer | Language | Key Libraries |
|-------|----------|---------------|
| Core library | Python | `pydantic`, `httpx`, `jmespath`, `sqlite3` (stdlib) |
| MCP Plugin | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog` |
| Connector Runtime | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog` |
| Studio UI | TypeScript | React, Vite, shadcn/ui, `@modelcontextprotocol/sdk` |

## Epic Summaries

### [01 — Monorepo Setup](01-monorepo-setup/)
Initialize the uv + pnpm workspace, shared Python/TypeScript tooling configs (pytest, mypy, ruff, ESLint), and per-package stubs. Done when `uv sync` and `pnpm install` both succeed.

### [02 — Core Library](02-core-library/)
The `elliot-core` Python package: Pydantic types, JSON flattener, SQLite engine, API/file/DB source fetchers, tool validator, tool registry, tool executor, skill runner, connector builder/serializer. Done when `uv run pytest` hits ≥ 95% coverage.

### [03 — MCP Plugin](03-mcp-plugin/)
The `elliot-mcp-plugin` package: `ElliotSession` singleton, `FastMCP` server factory on port 3000, all MCP tool groups (source, SQL, tool, skill, context, connector, studio meta-tools), FastAPI HTTP server, and install script for Claude Code.

### [04 — Connector Runtime](04-connector-runtime/)
The `elliot-connector-runtime` package on port 3001: loads a `.connector.json`, caches it with TTL + mtime, executes tools against live REST/DB sources via ephemeral SQLite, serves them as MCP, includes OpenAI-compatible `/v1/chat/completions` endpoint and NDJSON audit log.

### [05 — Studio UI](05-studio-ui/)
The `elliot-studio` TypeScript React app: Vite + shadcn/ui, React Router app shell, MCP client (StreamableHTTPClientTransport), Zustand store, all pages (Dashboard, Tools, Skills, Playground, Metrics/Audit).

### [06 — Eval & Polish](06-eval-and-polish/)
Evaluation runner + quality analyzer in `elliot-core`, eval page UI, error class hierarchy, error handling audit, empty states, end-to-end integration test, GitHub Actions CI workflow.

### [07 — DX & Observability](07-dx-and-observability/)
Structured JSON logging with `structlog` for both Python services (task 057), FastAPI global error middleware mapping `ElliotError` subclasses to HTTP status codes (task 058), and the full test strategy document covering pyramid, mocking rules, CI ordering, and coverage gates per package (task 059).
