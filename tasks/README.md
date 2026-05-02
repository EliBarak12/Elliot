# Elliot — Task List

56 ordered tasks across 4 sprints. Work them in numeric order — each task's output is needed by those that follow.

## Sprints

| Sprint | Tasks | Focus | Est. Hours |
|--------|-------|-------|------------|
| 1 | 001–021 | Monorepo + entire `@elliot/core` library | 40–48h |
| 2 | 022–032 | `@elliot/mcp-plugin` (agent can build connectors) | 28–34h |
| 3 | 033–037 | `@elliot/connector-runtime` (deployed MCP server) | 20–24h |
| 4 | 038–056 | `@elliot/studio` + evaluation + polish + CI | 40–48h |

**Total**: ~128–154 hours

## Task Index

### Sprint 1 — Core Foundation
- [001](001-root-workspace.md) Root workspace
- [002](002-typescript-vitest-config.md) TypeScript + Vitest config
- [003](003-lint-format-config.md) ESLint + Prettier
- [004](004-package-stubs.md) Package stubs + verify install
- [005](005-core-type-definitions.md) Core type definitions
- [006](006-column-namer-type-inferrer.md) Column namer + type inferrer
- [007](007-json-flattener.md) JSON flattener
- [008](008-flattener-tests.md) Flattener unit tests (15+ cases)
- [009](009-sqlite-engine.md) SQLiteEngine class
- [010](010-sql-query-validator.md) SQL query validator
- [011](011-sqlite-tests.md) SQLite unit + integration tests
- [012](012-api-fetcher.md) API fetcher (undici + pagination + retry)
- [013](013-file-reader.md) File reader (CSV / JSON / JSONL)
- [014](014-db-connector.md) DB connector (SQLite file + PostgreSQL)
- [015](015-source-tests.md) Source fetcher tests
- [016](016-tool-validator.md) Tool + skill validator (zod)
- [017](017-tool-registry.md) Tool registry
- [018](018-tool-executor.md) Tool executor
- [019](019-skill-runner.md) Skill runner + binding resolver
- [020](020-connector-builder-serializer.md) Connector builder + serializer
- [021](021-core-public-api.md) Core public API (index.ts) + core tests

### Sprint 2 — MCP Plugin
- [022](022-elliot-session.md) ElliotSession (state + secrets)
- [023](023-mcp-server-factory.md) MCP server factory
- [024](024-source-tools.md) Source MCP tools
- [025](025-sql-tools.md) SQL MCP tools
- [026](026-plugin-http-server.md) Plugin HTTP server (StreamableHTTP)
- [027](027-plugin-install-script.md) Auto-registration script
- [028](028-plugin-source-sql-tests.md) Plugin source + SQL integration tests
- [029](029-tool-tools.md) Tool MCP tools
- [030](030-skill-tools.md) Skill MCP tools
- [031](031-context-connector-tools.md) Context + connector MCP tools
- [032](032-plugin-build-flow-test.md) Plugin full build-flow integration test

### Sprint 3 — Connector Runtime
- [033](033-runtime-loader-cache.md) Runtime loader + TTL cache
- [034](034-runtime-executor.md) Runtime tool executor
- [035](035-runtime-mcp-server.md) Runtime MCP server (StreamableHTTP)
- [036](036-runtime-openai-audit.md) OpenAI protocol + audit log
- [037](037-runtime-tests.md) Runtime integration tests

### Sprint 4 — Studio + Evaluation + Polish
- [038](038-studio-vite-setup.md) Studio Vite + shadcn + Tailwind setup
- [039](039-studio-app-shell.md) App shell + router
- [040](040-studio-mcp-client.md) MCP client + React Query hooks
- [041](041-studio-zustand-store.md) Zustand store
- [042](042-studio-dashboard-sources.md) Dashboard + Sources page
- [043](043-studio-tools-page.md) Tools page + SQL editor
- [044](044-studio-skills-connector-page.md) Skills + Connector page
- [045](045-studio-meta-tools.md) Studio meta-tools on plugin
- [046](046-studio-playground.md) Playground page
- [047](047-studio-metrics.md) Metrics page
- [048](048-studio-ui-tests.md) Studio unit tests
- [049](049-eval-runner.md) Evaluation runner
- [050](050-quality-analyzer.md) Description quality analyzer
- [051](051-eval-page.md) Evaluation page UI
- [052](052-elliot-error-class.md) ElliotError class
- [053](053-error-handling-audit.md) Error handling audit
- [054](054-studio-empty-states.md) Studio empty states + toasts
- [055](055-e2e-integration-test.md) End-to-end integration test
- [056](056-ci-workflow.md) CI workflow (GitHub Actions)
