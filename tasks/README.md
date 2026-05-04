# Elliot — Task List

75 ordered tasks across 9 epics. The **Folder Structure** table below is for navigation. The **Build Order** table is the sequence to actually implement them — each phase unlocks the next.

**Backend**: Python 3.12 + uv workspaces 
**Frontend**: TypeScript + React + Vite + shadcn/ui

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
| [09-platform-and-builder](09-platform-and-builder/) | 068–075 | Auth, deployment, agentic builder, connector editor, multi-connector, rate limiting, templates |

**Total**: ~214–266 hours

---

## Build Order

Tasks are grouped into 8 phases. Complete each phase before starting the next — each one is a hard dependency for everything below it.

### Phase 1 — Foundation
*Nothing else can start until this is done. Sets up the workspace, shared types, error classes, logging, and security baseline.*

| # | Task | File | What it unlocks |
|---|------|------|-----------------|
| 1 | 001 | [monorepo-workspace](01-monorepo-setup/001-monorepo-workspace.md) | `uv sync` + `pnpm install` succeed |
| 2 | 002 | [python-tooling](01-monorepo-setup/002-python-tooling.md) | ruff, mypy, pytest configured |
| 3 | 003 | [typescript-tooling](01-monorepo-setup/003-typescript-tooling.md) | ESLint, Vitest configured |
| 4 | 004 | [package-stubs](01-monorepo-setup/004-package-stubs.md) | All packages importable |
| 5 | 005 | [core-type-definitions](02-core-library/005-core-type-definitions.md) | `ConnectorConfig`, `ToolDefinition`, all Pydantic models |
| 6 | 052 | [elliot-error-class](06-eval-and-polish/052-elliot-error-class.md) | `ElliotError` hierarchy — used by every service |
| 7 | 057 | [structured-logging](07-dx-and-observability/057-structured-logging.md) | `structlog` JSON logging in both services |
| 8 | 058 | [error-middleware](07-dx-and-observability/058-error-middleware.md) | `ElliotError` → HTTP status mapping |
| 9 | 068 | [api-key-auth](09-platform-and-builder/068-api-key-auth.md) | `X-Elliot-Key` security on all endpoints |
| 10 | 066 | [secrets-management](08-agent-observability/066-secrets-management.md) | `{{ env:VAR }}` placeholders in connector.json |

### Phase 2 — Core Library
*The shared Python engine. All three backend services import from here. Build in this exact order — each module depends on the previous ones.*

| # | Task | File | What it unlocks |
|---|------|------|-----------------|
| 11 | 006 | [column-namer-type-inferrer](02-core-library/006-column-namer-type-inferrer.md) | Column names + type inference from raw data |
| 12 | 007 | [json-flattener](02-core-library/007-json-flattener.md) | Nested JSON → flat rows |
| 13 | 008 | [flattener-tests](02-core-library/008-flattener-tests.md) | Flattener coverage |
| 14 | 009 | [sqlite-engine](02-core-library/009-sqlite-engine.md) | In-memory SQLite ingest + query |
| 15 | 010 | [sql-query-validator](02-core-library/010-sql-query-validator.md) | Safe SQL validation |
| 16 | 011 | [sqlite-tests](02-core-library/011-sqlite-tests.md) | SQLite engine coverage |
| 17 | 012 | [api-fetcher](02-core-library/012-api-fetcher.md) | REST API fetch + auth |
| 18 | 013 | [file-reader](02-core-library/013-file-reader.md) | CSV / JSON file source |
| 19 | 014 | [db-connector](02-core-library/014-db-connector.md) | PostgreSQL / MySQL direct connect |
| 20 | 015 | [source-tests](02-core-library/015-source-tests.md) | All fetcher coverage |
| 21 | 016 | [tool-validator](02-core-library/016-tool-validator.md) | Validates `ToolDefinition` before registration |
| 22 | 017 | [tool-registry](02-core-library/017-tool-registry.md) | Tool lookup by ID |
| 23 | 018 | [tool-executor](02-core-library/018-tool-executor.md) | `ToolExecutor`: fetch → SQLite → result |
| 24 | 019 | [skill-runner](02-core-library/019-skill-runner.md) | Multi-step skill execution |
| 25 | 020 | [connector-builder-serializer](02-core-library/020-connector-builder-serializer.md) | Build + save connector.json |
| 26 | 021 | [core-public-api](02-core-library/021-core-public-api.md) | Clean `__init__.py` exports |

### Phase 3 — Connector Creation Tools
*How users define their tools — templates, auto-generation from specs, and quality checks. Build before the runtime so the linter and secrets resolver are available when the runtime loads connectors.*

| # | Task | File | What it unlocks |
|---|------|------|-----------------|
| 27 | 059 | [test-plan](07-dx-and-observability/059-test-plan.md) | Test strategy doc — guides all subsequent test writing |
| 28 | 075 | [connector-templates](09-platform-and-builder/075-connector-templates.md) | `elliot init --template` — fastest path to first connector |
| 29 | 070 | [openapi-spec-analyzer](09-platform-and-builder/070-openapi-spec-analyzer.md) | Parse OpenAPI spec → `ProposedConnector` |
| 30 | 061 | [tool-quality-linter](08-agent-observability/061-tool-quality-linter.md) | `elliot lint` — static quality check before deploy |
| 31 | 062 | [eval-test-cases](08-agent-observability/062-eval-test-cases.md) | YAML eval schema — Pydantic models for test cases |

### Phase 4 — Runtime Services
*The execution infrastructure. Loads connectors, runs tools, stores observations. The runtime is what agents actually call.*

| # | Task | File | What it unlocks |
|---|------|------|-----------------|
| 32 | 033 | [runtime-loader-cache](04-connector-runtime/033-runtime-loader-cache.md) | `ConnectorCache` — TTL + mtime reload |
| 33 | 034 | [runtime-executor](04-connector-runtime/034-runtime-executor.md) | `ToolExecutor` in the runtime — REST + SQL |
| 34 | 067 | [local-observation-store](08-agent-observability/067-local-observation-store.md) | SQLAlchemy store (SQLite default / MySQL optional) |
| 35 | 060 | [agent-session-tracker](08-agent-observability/060-agent-session-tracker.md) | Session grouping on top of observation store |
| 36 | 035 | [runtime-mcp-server](04-connector-runtime/035-runtime-mcp-server.md) | FastMCP server on :3001 |
| 37 | 036 | [runtime-openai-audit](04-connector-runtime/036-runtime-openai-audit.md) | `/v1/chat/completions` + audit wired to store |
| 38 | 037 | [runtime-tests](04-connector-runtime/037-runtime-tests.md) | Full runtime test suite |
| 39 | 073 | [multi-connector-runtime](09-platform-and-builder/073-multi-connector-runtime.md) | Directory mode — one process, all connectors |
| 40 | 074 | [rate-limiting](09-platform-and-builder/074-rate-limiting.md) | `slowapi` 429 protection on tool endpoints |

### Phase 5 — MCP Plugin & Agentic Builder
*The agent-facing interface AND the tools that let an agent build new connectors interactively. The agentic builder (071) requires both the plugin and the OpenAPI analyzer (070) to exist first.*

| # | Task | File | What it unlocks |
|---|------|------|-----------------|
| 41 | 022 | [plugin-session](03-mcp-plugin/022-plugin-session.md) | `ElliotSession` singleton |
| 42 | 023 | [plugin-fastmcp-server](03-mcp-plugin/023-plugin-fastmcp-server.md) | FastMCP server factory on :3000 |
| 43 | 024 | [plugin-source-tools](03-mcp-plugin/024-plugin-source-tools.md) | MCP tools: list sources, preview data |
| 44 | 025 | [plugin-sql-tools](03-mcp-plugin/025-plugin-sql-tools.md) | MCP tools: run SQL against sources |
| 45 | 026 | [plugin-skill-tools](03-mcp-plugin/026-plugin-skill-tools.md) | MCP tools: run skills |
| 46 | 027 | [plugin-context-tools](03-mcp-plugin/027-plugin-context-tools.md) | MCP tools: connector metadata |
| 47 | 028 | [plugin-connector-meta-tools](03-mcp-plugin/028-plugin-connector-meta-tools.md) | MCP tools: list/load connectors |
| 48 | 029 | [plugin-studio-meta-tools](03-mcp-plugin/029-plugin-studio-meta-tools.md) | MCP tools: Studio status |
| 49 | 030 | [plugin-fastapi-server](03-mcp-plugin/030-plugin-fastapi-server.md) | FastAPI HTTP layer on :3000 |
| 50 | 031 | [plugin-install-script](03-mcp-plugin/031-plugin-install-script.md) | `elliot install` for Claude Code |
| 51 | 032 | [plugin-tests](03-mcp-plugin/032-plugin-tests.md) | Full plugin test suite |
| 52 | 071 | [agentic-connector-builder](09-platform-and-builder/071-agentic-connector-builder.md) | Agent builds connectors via MCP tools — the core product moment |

### Phase 6 — Studio UI
*The visual layer for observing and improving. Build after the runtime and plugin are running so the Studio has real data to display.*

| # | Task | File | What it unlocks |
|---|------|------|-----------------|
| 53 | 038 | [studio-vite-setup](05-studio-ui/038-studio-vite-setup.md) | Vite + shadcn/ui + React Router scaffold |
| 54 | 039 | [studio-app-shell](05-studio-ui/039-studio-app-shell.md) | Nav sidebar, layout, routing |
| 55 | 040 | [studio-mcp-client](05-studio-ui/040-studio-mcp-client.md) | `StreamableHTTPClientTransport` connection |
| 56 | 041 | [studio-zustand-store](05-studio-ui/041-studio-zustand-store.md) | Global state (connector, tools, sessions) |
| 57 | 042 | [studio-dashboard](05-studio-ui/042-studio-dashboard-sources.md) | Sources overview page |
| 58 | 043 | [studio-tools-page](05-studio-ui/043-studio-tools-page.md) | Tool browser + manual runner |
| 59 | 044 | [studio-skills-page](05-studio-ui/044-studio-skills-connector-page.md) | Skills browser |
| 60 | 045 | [studio-meta-tools](05-studio-ui/045-studio-meta-tools.md) | Connector meta-tool UI |
| 61 | 046 | [studio-playground](05-studio-ui/046-studio-playground.md) | Interactive tool tester |
| 62 | 047 | [studio-metrics](05-studio-ui/047-studio-metrics.md) | Audit log + metrics page |
| 63 | 048 | [studio-ui-tests](05-studio-ui/048-studio-ui-tests.md) | Studio component tests |
| 64 | 064 | [studio-agent-console](08-agent-observability/064-studio-agent-console.md) | Real-time session tree: agent → tool calls → tokens |
| 65 | 065 | [token-efficiency-metrics](08-agent-observability/065-token-efficiency-metrics.md) | Per-tool avg tokens, risk levels, suggestions |
| 66 | 072 | [connector-editor-ui](09-platform-and-builder/072-connector-editor-ui.md) | Visual connector editor — close the improve loop |

### Phase 7 — Quality Gates
*Eval runner, quality analyzer, error audit, and UI polish. These validate that what was built actually works end-to-end.*

| # | Task | File | What it unlocks |
|---|------|------|-----------------|
| 67 | 063 | [eval-runner-cli](08-agent-observability/063-eval-runner.md) | `elliot eval` — async runner against live runtime |
| 68 | 049 | [eval-runner-core](06-eval-and-polish/049-eval-runner.md) | Core eval logic in `elliot-core` |
| 69 | 050 | [quality-analyzer](06-eval-and-polish/050-quality-analyzer.md) | Tool quality scoring |
| 70 | 051 | [eval-page-ui](06-eval-and-polish/051-eval-page.md) | Eval results in Studio |
| 71 | 053 | [error-handling-audit](06-eval-and-polish/053-error-handling-audit.md) | Verify all errors are structured + actionable |
| 72 | 054 | [studio-empty-states](06-eval-and-polish/054-studio-empty-states.md) | Empty states for first-time users |

### Phase 8 — Ship
*Integration test, CI pipeline, and production packaging. Nothing here can happen until the full stack is working.*

| # | Task | File | What it unlocks |
|---|------|------|-----------------|
| 73 | 055 | [e2e-integration-test](06-eval-and-polish/055-e2e-integration-test.md) | Full stack test: agent → plugin → runtime → DB |
| 74 | 056 | [ci-workflow](06-eval-and-polish/056-ci-workflow.md) | GitHub Actions: lint → test → build on every PR |
| 75 | 069 | [docker-compose-deployment](09-platform-and-builder/069-docker-compose-deployment.md) | `docker compose up` — full production stack |

---

## Tech Stack

| Layer | Language | Key Libraries |
|-------|----------|---------------|
| Core library | Python | `pydantic`, `httpx`, `jmespath`, `sqlite3` (stdlib) |
| MCP Plugin | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog`, `slowapi` |
| Connector Runtime | Python | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog`, `sqlalchemy`, `pymysql`, `slowapi` |
| Studio UI | TypeScript | React, Vite, shadcn/ui, `@modelcontextprotocol/sdk` |

---

## Epic Summaries

### [01 — Monorepo Setup](01-monorepo-setup/)
Initialize the uv + pnpm workspace, shared Python/TypeScript tooling configs, and per-package stubs.

### [02 — Core Library](02-core-library/)
`elliot-core`: Pydantic types, JSON flattener, SQLite engine, source fetchers, tool validator, registry, executor, skill runner, connector builder. Target: ≥ 95% test coverage.

### [03 — MCP Plugin](03-mcp-plugin/)
`elliot-mcp-plugin` on :3000: `ElliotSession`, FastMCP server, all MCP tool groups, FastAPI HTTP layer, Claude Code install script.

### [04 — Connector Runtime](04-connector-runtime/)
`elliot-connector-runtime` on :3001: connector loader + cache, tool executor, FastMCP server, OpenAI-compatible endpoint, observation store.

### [05 — Studio UI](05-studio-ui/)
`elliot-studio` React app on :5173: app shell, MCP client, Zustand store, all pages (Dashboard, Tools, Skills, Playground, Metrics).

### [06 — Eval & Polish](06-eval-and-polish/)
Eval runner, quality analyzer, eval UI page, error hierarchy, error audit, empty states, E2E integration test, GitHub Actions CI.

### [07 — DX & Observability](07-dx-and-observability/)
`structlog` JSON logging, FastAPI error middleware, test strategy document.

### [08 — Agent Observability](08-agent-observability/)
Agent session tracker, tool quality linter (`elliot lint`), eval YAML schema, eval runner CLI (`elliot eval`), Studio Agent Console, token efficiency metrics, secrets management (`{{ env:VAR }}`), SQLAlchemy observation store (SQLite/MySQL).

### [09 — Platform & Agentic Builder](09-platform-and-builder/)
API key auth, Docker Compose deployment, OpenAPI spec analyzer, agentic connector builder MCP tools (agent builds your connector interactively), connector editor UI in Studio, multi-connector runtime directory mode, rate limiting, connector starter templates.
