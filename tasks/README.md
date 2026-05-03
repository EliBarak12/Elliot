# Elliot — Task List

56 ordered tasks across 4 sprints, organized into 6 epic folders.

**Backend**: Python 3.12 + uv workspaces  
**Frontend**: TypeScript + React + Vite + shadcn/ui (unchanged)

## Folder Structure

| Folder | Sprint | Tasks | Focus | Est. Hours |
|--------|--------|-------|-------|------------|
| [01-monorepo-setup](01-monorepo-setup/) | 1 | 001–004 | Workspace, config, tooling | 4–5h |
| [02-core-library](02-core-library/) | 1 | 005–021 | `elliot-core` Python library | 36–43h |
| [03-mcp-plugin](03-mcp-plugin/) | 2 | 022–032 | `elliot-mcp-plugin` (FastMCP + FastAPI) | 28–34h |
| [04-connector-runtime](04-connector-runtime/) | 3 | 033–037 | `elliot-connector-runtime` (deployed MCP) | 20–24h |
| [05-studio-ui](05-studio-ui/) | 4 | 038–048 | Studio React app (TypeScript) | 30–36h |
| [06-eval-and-polish](06-eval-and-polish/) | 4 | 049–056 | Eval, quality, CI | 18–22h |

**Total**: ~128–154 hours

## Tech Stack

| Layer | Language | Key Libraries |
|-------|----------|--------------|
| Core library | Python | `pydantic`, `httpx`, `sqlite3` (stdlib), `cryptography` |
| MCP Plugin | Python | `mcp` (Python SDK), `fastapi`, `uvicorn` |
| Connector Runtime | Python | `mcp`, `fastapi`, `uvicorn` |
| Studio UI | TypeScript | React, Vite, shadcn/ui, `@modelcontextprotocol/sdk` |

## Epic Summaries

### [01 — Monorepo Setup](01-monorepo-setup/)
Initialize the uv + pnpm workspace, shared Python/TypeScript tooling configs (pytest, mypy, ruff, ESLint), and per-package stubs. Done when `uv sync` and `pnpm install` both succeed.

### [02 — Core Library](02-core-library/)
The `elliot-core` Python package: Pydantic types, JSON flattener, SQLite engine, API/file/DB source fetchers, tool validator, tool registry, tool executor, skill runner, connector builder/serializer. Done when `uv run pytest` hits ≥ 85% coverage.

### [03 — MCP Plugin](03-mcp-plugin/)
The `elliot-mcp-plugin` package: `ElliotSession` singleton, `FastMCP` server factory, all MCP tool groups (source, SQL, tool, skill, context, connector, studio meta-tools), FastAPI HTTP server, and auto-registration install script.

### [04 — Connector Runtime](04-connector-runtime/)
The `elliot-connector-runtime` package: loads a `.connector.json`, caches it with TTL, executes tools against live sources, serves them as MCP over HTTP on port 3001. Also includes an OpenAI-compatible `/v1/chat/completions` endpoint and NDJSON audit log.

### [05 — Studio UI](05-studio-ui/)
The `@elliot/studio` TypeScript React app: Vite + shadcn/ui, React Router app shell, MCP client (StreamableHTTPClientTransport), Zustand store, all 8 pages (Dashboard, Sources, Tools, Skills, Connector, Playground, Metrics, Evaluation).

### [06 — Eval & Polish](06-eval-and-polish/)
Evaluation runner + quality analyzer in `elliot-core`, eval page UI, error handling audit, empty states, toasts, end-to-end integration test, and GitHub Actions CI workflow.
