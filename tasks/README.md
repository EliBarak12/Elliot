# Elliot — Task List

79 ordered tasks across 9 epics. The **Folder Structure** table is for navigation. The **Build Order** is the sequence to implement them.

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

**Total**: ~230–285 hours

---

## Tech Stack

| Layer | Language | Key Libraries |
|-------|----------|---------------|
| Core library | Python | `pydantic`, `httpx`, `sqlite3`, `sqlalchemy` |
| MCP Plugin | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog`, `slowapi` |
| Connector Runtime | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog`, `sqlalchemy`, `pymysql`, `asyncpg` |
| Studio UI | TypeScript | React 19, Vite, shadcn/ui, TanStack Router v1, TanStack Query v5, TanStack Table v8, Zustand v5, `@modelcontextprotocol/sdk` |
