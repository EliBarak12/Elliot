> ⚠️ **Migration notice — this document covers the original TypeScript design.**
> The backend has moved to **Python 3.12 + uv workspaces**. The domain model and concepts remain valid; the implementation language and libraries differ.
>
> **For current diagrams see:**
> - [`docs/architecture.md`](architecture.md) — system graph, package deps, directory tree, Pydantic class diagram
> - [`docs/data-flow.md`](data-flow.md) — sequence diagrams: tool call, cache load, Studio UI flow, error handling
> - [`docs/product-overview.md`](product-overview.md) — user journey, Studio pages, component tree

---

# Elliot — Architecture (original TypeScript design, kept for reference)

> The content below describes the original TypeScript monorepo design.
> Key differences in the current Python implementation:
>
> | Concept | Original (TS) | Current (Python) |
> |---|---|---|
> | Package manager | pnpm only | uv (Python) + pnpm (Studio) |
> | MCP server lib | `@modelcontextprotocol/sdk` | `mcp` (FastMCP) |
> | Schema validation | `zod` | `pydantic` |
> | SQLite | `better-sqlite3` | `sqlite3` stdlib |
> | HTTP client | `undici` | `httpx` (async) |
> | JSON path | custom | `jmespath` |
> | Logging | `pino` / `winston` | `structlog` (JSON) |
> | Testing | `vitest` | `pytest` + `pytest-asyncio` + `respx` |

---

<!--  Original TypeScript architecture content preserved below for reference  -->
