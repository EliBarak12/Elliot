# Elliot — Development Missions

12 sequential missions. Each one produces working, tested code. Complete them in order.

**Stack**: TypeScript 5, pnpm workspaces, `better-sqlite3`, `@modelcontextprotocol/sdk`, React + Vite + shadcn/ui + Tailwind, Vitest.

**Total estimated time**: 95–125 hours

---

## Mission 1: Monorepo Foundation
**Estimated**: 3–4 hours | **Dependencies**: None

### Objective
Set up the pnpm monorepo with shared TypeScript config, ESLint, Prettier, and Vitest workspace. No business logic yet — just infrastructure.

### Steps

1. Initialize root `package.json` with pnpm workspaces
2. Create `pnpm-workspace.yaml` pointing to `packages/*`
3. Create `tsconfig.base.json` (strict, ES2022, bundler resolution)
4. Create `vitest.workspace.ts` pointing to all package vitest configs
5. Set up ESLint (`@typescript-eslint`) + Prettier configs at root
6. Add `.gitignore` (node_modules, dist, .elliot/secrets.enc, *.connector.json)
7. Create stub `package.json` for each of the 4 packages with correct `name`, `type: "module"`, `exports`
8. Verify `pnpm install` works and `pnpm -r run typecheck` produces no errors

### Files Created
```
package.json                pnpm-workspace.yaml
tsconfig.base.json          vitest.workspace.ts
.eslintrc.cjs               .prettierrc
.gitignore
packages/core/package.json
packages/mcp-plugin/package.json
packages/connector-runtime/package.json
packages/studio/package.json
```

### Acceptance Criteria
- `pnpm install` succeeds
- `pnpm -r run typecheck` exits 0 (even if packages are empty)
- Workspace package imports work (e.g., `@elliot/core` resolvable from `@elliot/mcp-plugin`)

---

## Mission 2: Core — Source Types & JSON Flattener
**Estimated**: 10–12 hours | **Dependencies**: Mission 1

### Objective
Implement the JSON flattening engine — the most critical component in Elliot. Every piece of data passes through this.

### Steps

**2.1** Define all types in `packages/core/src/sources/types.ts` and `packages/core/src/tools/types.ts` (see ARCHITECTURE.md Section 3 for full TypeScript interfaces)

**2.2** Implement `packages/core/src/sqlite/flattener.ts`:
- Traverse arbitrary JSON recursively using `WeakSet` for circular detection
- Primitives → column in parent table
- Objects → flattened with `_` separator
- Arrays of primitives → serialized to JSON string as TEXT column
- Arrays of objects → related table with `_parent_id` FK
- Nesting depth > 5 → serialize as TEXT with warning
- Apply `safeName()` for SQL reserved keywords and collisions
- Emit typed `FlattenWarning[]` array

**2.3** Implement `packages/core/src/sqlite/type-inferrer.ts`:
- Infer `INTEGER | REAL | TEXT` from array of sample values
- Detect formats: `iso_date`, `uuid`, `email`, `boolean_string`

**2.4** Write unit tests — **minimum 15 test cases** covering ALL documented edge cases:
```
flattener.test.ts:
  - nested object flattening
  - array of objects → related table
  - array of primitives → JSON string
  - depth > 5 → serialized
  - circular reference → warning + replacement
  - mixed types → TEXT
  - reserved keyword → renamed + warning
  - name collision → _2 suffix
  - empty object → nulls row
  - empty array → empty related table
  - array > 1000 items → truncated + warning
  - null values → NULL
  - boolean → INTEGER 0/1
  - large integer (> MAX_SAFE_INTEGER) → TEXT
  - unicode key names → normalized
```

### Files Created
```
packages/core/src/sources/types.ts
packages/core/src/tools/types.ts
packages/core/src/sqlite/flattener.ts
packages/core/src/sqlite/type-inferrer.ts
packages/core/src/sqlite/column-namer.ts
packages/core/tests/unit/flattener.test.ts
packages/core/tests/unit/type-inferrer.test.ts
```

### Acceptance Criteria
- All 15+ flattener unit tests pass
- Type coverage ≥ 85%
- No `any` types in production code

---

## Mission 3: Core — SQLite Engine & Query Runner
**Estimated**: 6–8 hours | **Dependencies**: Mission 2

### Objective
Build the `SQLiteEngine` class (in-memory `better-sqlite3`) and the safe query runner with SQL validation.

### Steps

**3.1** Implement `packages/core/src/sqlite/engine.ts`:
- `SQLiteEngine` class with in-memory `better-sqlite3` database
- `loadTable(FlattenedTable)` — CREATE TABLE + batch INSERT
- `query(sql, params)` — execute SELECT with named params
- `getTableNames()`, `getTableSchema(tableName)`, `getTableStats(tableName)`
- `profileColumn(tableName, columnName)` — cardinality, nulls, min, max, top-5 values
- `close()`

**3.2** Implement `packages/core/src/sqlite/query-runner.ts`:
- `validateToolSql(sql)` — whitelist SELECT only; reject DDL, multiple statements
- Guard against: `DROP`, `CREATE`, `ALTER`, `INSERT`, `UPDATE`, `DELETE`, `ATTACH`, `PRAGMA`, `--`, `;` inside strings
- Must start with `SELECT` (after trimming whitespace and comments)
- `runToolQuery(db, sql, params)` — bind params via `better-sqlite3` named params

**3.3** Write unit tests:
```
engine.test.ts:
  - load table and query it
  - parameterized query returns correct rows
  - empty table returns []
  - profile column returns accurate stats
  - close() prevents further queries

query-runner.test.ts:
  - valid SELECT passes
  - DROP TABLE rejected
  - multiple statements rejected
  - PRAGMA rejected
  - SQL comment injection rejected (-- ...)
  - non-SELECT rejected
  - named params bound correctly
  - missing required param → error
```

**3.4** Write integration test spinning up a real engine and running multi-table JOIN queries.

### Files Created
```
packages/core/src/sqlite/engine.ts
packages/core/src/sqlite/query-runner.ts
packages/core/tests/unit/engine.test.ts
packages/core/tests/unit/query-runner.test.ts
packages/core/tests/integration/sqlite-engine.test.ts
```

### Acceptance Criteria
- All SQL validator tests pass (especially injection attempts)
- Integration test: 3-table JOIN query returns correct data
- `better-sqlite3` performs synchronously — no async/await in engine

---

## Mission 4: Core — Source Fetchers
**Estimated**: 10–12 hours | **Dependencies**: Mission 3

### Objective
Implement the three source fetchers: REST API, file (CSV/JSON), and direct database connection.

### Steps

**4.1** `packages/core/src/sources/api-fetcher.ts` using `undici`:
- Fetch a single endpoint (with auth injection)
- Handle response envelope unwrapping (`data.items`, `results`, etc.)
- Auto-paginate: cursor, offset, page, link-header strategies
- Hard limit: `maxPages` (default 100)
- Retry on 429 (read `Retry-After`), 500, 503 (up to 3 times)
- Redact auth headers from all logs
- Return `FetchResult: { rows: unknown[], warnings: FetchWarning[], fetchedAt: Date }`

**4.2** `packages/core/src/sources/file-reader.ts`:
- CSV: `papaparse` with header detection, encoding, delimiter config
- JSON: handle both `[...]` and `{ data: [...] }` shape
- JSONL: stream line by line, parse each as JSON, collect to array
- Report file size and encoding warnings

**4.3** `packages/core/src/sources/db-connector.ts`:
- `better-sqlite3` for local SQLite files
- `pg` for PostgreSQL (SELECT queries only, read-only connection)
- Execute named `DbQueryConfig.sql` and return rows
- Connection validation on first connect

**4.4** `packages/core/src/sources/schema-detector.ts`:
- Given an array of raw JSON rows, produce `ColumnMeta[]`
- Sample first 100 rows for type inference
- Return `schemaFingerprint` (stable hash of column names + types for drift detection)

**4.5** Write integration tests using local mock HTTP server (Node `http.createServer`):
- Pagination test: server returns pages, client collects all
- Rate limit test: server returns 429 on first request, client retries
- Auth injection test: server validates `X-API-Key` header
- Envelope unwrapping: `{ data: { items: [...] } }` → flat array

**4.6** Write unit tests for file reader with fixture files in `tests/fixtures/`.

### Files Created
```
packages/core/src/sources/api-fetcher.ts
packages/core/src/sources/file-reader.ts
packages/core/src/sources/db-connector.ts
packages/core/src/sources/schema-detector.ts
packages/core/src/sources/paginator.ts
packages/core/tests/fixtures/customers.csv
packages/core/tests/fixtures/orders.json
packages/core/tests/integration/api-fetcher.test.ts
packages/core/tests/unit/file-reader.test.ts
packages/core/tests/unit/schema-detector.test.ts
```

### Acceptance Criteria
- Paginated API fetches all pages (tested with mock server)
- CSV/JSON files parsed correctly with all edge cases covered
- Auth headers injected but never logged in plaintext
- Schema drift detected and reported correctly

---

## Mission 5: Core — Tool Registry, Validator & Executor
**Estimated**: 8–10 hours | **Dependencies**: Mission 4

### Objective
Build the tool management layer: defining, validating, storing, and executing tools.

### Steps

**5.1** `packages/core/src/tools/validator.ts`:
- Zod schemas for `ToolDefinition`, `SkillDefinition`, `ConnectorConfig`
- Validate `tool.sql` (must be SELECT, no DDL)
- Validate `tool.parameters` are all referenced in SQL (`:param_name` present for each)
- Validate no orphaned SQL params (`:param` in SQL but not in parameters)

**5.2** `packages/core/src/tools/registry.ts`:
- `ToolRegistry` class: in-memory Map of tools and skills
- `add(tool)`, `update(toolId, partial)`, `delete(toolId)`
- `get(toolId)`, `getByName(name)`, `getAll()`
- Same for skills
- `validate(tool)` — runs Zod + SQL validation
- Name uniqueness enforcement

**5.3** `packages/core/src/tools/executor.ts`:
- `executeTool(tool, params, engine)`:
  1. Validate params against `tool.parameters` (type coercion for safe cases)
  2. Re-validate SQL (defense in depth)
  3. Run `engine.query(tool.sql, boundParams)`
  4. Apply `responseShape` (field filter, rename, maxRows)
  5. Add `_meta` object if `includeMetadata: true`
  6. Return `ToolResult: { rows, meta: { rowCount, latencyMs, truncated } }`
- `executeSkill(skill, inputs, registry, engine)` — sequential step runner with binding resolver
- Binding resolver: `{{skill.input.X}}` and `{{steps.ALIAS.FIELD}}`

**5.4** `packages/core/src/connector/builder.ts` and `serializer.ts`:
- `ConnectorBuilder.build(config)` — validate and assemble `ConnectorConfig`
- `serializeConnector(config)` → JSON string
- `deserializeConnector(json)` → validated `ConnectorConfig`

**5.5** Write unit tests:
```
validator.test.ts:
  - valid tool passes
  - SQL with DDL rejected
  - param in SQL but not in definition → error
  - param in definition but not in SQL → warning

executor.test.ts:
  - correct rows returned for SELECT with params
  - empty result returns []
  - maxRows truncation works
  - responseShape field filter works
  - type coercion: "42" → 42 for integer param
  - wrong type for param that can't be coerced → error

skill-executor.test.ts:
  - sequential steps pass data correctly
  - {{skill.input.X}} binding works
  - {{steps.ALIAS.FIELD}} binding works
  - step failure aborts skill with partial result
```

### Files Created
```
packages/core/src/tools/validator.ts
packages/core/src/tools/registry.ts
packages/core/src/tools/executor.ts
packages/core/src/connector/builder.ts
packages/core/src/connector/serializer.ts
packages/core/src/connector/schema-gen.ts
packages/core/src/index.ts              ← export all public APIs
packages/core/tests/unit/validator.test.ts
packages/core/tests/unit/executor.test.ts
packages/core/tests/unit/skill-executor.test.ts
```

### Acceptance Criteria
- Tool execution returns correct data against in-memory SQLite
- Skill step binding resolves correctly for all template patterns
- Connector serializes and deserializes with identical output
- `@elliot/core` exports a clean public API

---

## Mission 6: MCP Plugin — Server & Source Tools
**Estimated**: 8–10 hours | **Dependencies**: Mission 5

### Objective
Build the MCP plugin server with source management and SQL exploration tools. After this mission, Claude Code can discover and query a user's APIs.

### Steps

**6.1** `packages/mcp-plugin/src/session.ts`:
- `ElliotSession` class holding `SQLiteEngine`, `ToolRegistry`, `ConnectorBuilder`
- `load()` / `save()` to `.elliot/session.json`
- Encrypted secrets storage in `.elliot/secrets.enc` (AES-256-GCM via Node crypto)

**6.2** `packages/mcp-plugin/src/server.ts`:
- Create `McpServer` from `@modelcontextprotocol/sdk`
- Call all `register*Tools(server, session)` functions

**6.3** `packages/mcp-plugin/src/tools/source-tools.ts` — implement:
- `elliot_discover_source`: fetch source, flatten, load SQLite, return schema summary
- `elliot_list_sources`: list all sources with row counts and table names
- `elliot_preview_source`: return first N rows from a table
- `elliot_profile_source`: column statistics for a table
- `elliot_refresh_source`: re-fetch and reload
- `elliot_remove_source`: remove source and drop its tables

**6.4** `packages/mcp-plugin/src/tools/sql-tools.ts` — implement:
- `elliot_get_schema`: all tables + columns
- `elliot_query_sql`: run SELECT (validated)
- `elliot_sample_data`: random N rows
- `elliot_profile_column`: column stats
- `elliot_explain_query`: EXPLAIN QUERY PLAN

**6.5** `packages/mcp-plugin/src/index.ts` — stdio entry point

**6.6** `scripts/install-claude.mjs` — write MCP config to `~/.claude/claude_desktop_config.json`

**6.7** Write MCP integration tests using `InMemoryTransport`:
- `elliot_discover_source` with CSV fixture file → returns schema
- `elliot_query_sql` → returns rows
- `elliot_profile_column` → correct stats

### Files Created
```
packages/mcp-plugin/src/session.ts
packages/mcp-plugin/src/server.ts
packages/mcp-plugin/src/index.ts
packages/mcp-plugin/src/tools/source-tools.ts
packages/mcp-plugin/src/tools/sql-tools.ts
packages/mcp-plugin/scripts/install-claude.mjs
packages/mcp-plugin/tests/integration/source-tools.test.ts
packages/mcp-plugin/tests/integration/sql-tools.test.ts
```

### Acceptance Criteria
- `pnpm run install-claude` registers the plugin in Claude Code config
- Claude Code can call `elliot_discover_source` and get a schema back
- `elliot_query_sql` returns real data from loaded tables
- Session state survives restart (load/save works)

---

## Mission 7: MCP Plugin — Tool & Connector Tools
**Estimated**: 6–8 hours | **Dependencies**: Mission 6

### Objective
Complete the MCP plugin with tool building, skill building, and connector management tools. After this mission, Claude Code can build and start a complete connector.

### Steps

**7.1** `packages/mcp-plugin/src/tools/tool-tools.ts`:
- `elliot_create_tool`: validate + add to registry + save
- `elliot_update_tool`: partial update + re-validate + save
- `elliot_list_tools`: all tools with metadata
- `elliot_get_tool`: full definition
- `elliot_delete_tool`: remove from registry + save
- `elliot_preview_tool`: re-fetch sources if needed, run SQL, return result
- `elliot_validate_sql`: validate without executing

**7.2** `packages/mcp-plugin/src/tools/skill-tools.ts`:
- `elliot_create_skill`: validate steps reference existing tools + save
- `elliot_list_skills`, `elliot_preview_skill`, `elliot_delete_skill`

**7.3** `packages/mcp-plugin/src/tools/context-tools.ts`:
- `elliot_set_product_context`: set and save product context
- `elliot_get_session_state`: return full session summary (sources, tools, skills, connector status)

**7.4** `packages/mcp-plugin/src/tools/connector-tools.ts`:
- `elliot_build_connector`: assemble ConnectorConfig from selected tool/skill IDs
- `elliot_get_connector`: current connector state
- `elliot_export_connector`: write `.connector.json` to disk
- `elliot_start_runtime`: spawn `@elliot/connector-runtime` as child process
- `elliot_stop_runtime`: kill child process
- `elliot_get_connection_config`: return formatted config snippet for Claude Desktop / Cursor

**7.5** Write integration tests for the full build flow:
- discover source → create tool → build connector → export file
- Connector JSON is valid and deserializes correctly

### Acceptance Criteria
- Claude Code can execute the full Phase 1 flow (see DEVELOPMENT_GUIDE Section 8)
- Built connector file is valid `ConnectorConfig`
- `elliot_start_runtime` starts the connector and reports the port
- `elliot_get_connection_config` returns correct Claude Desktop JSON

---

## Mission 8: Connector Runtime
**Estimated**: 10–12 hours | **Dependencies**: Mission 5

### Objective
Build the connector runtime — the MCP server that AI agents connect to to use a deployed connector.

### Steps

**8.1** `packages/connector-runtime/src/loader.ts`:
- Load + validate `.connector.json`
- Decrypt and reconstruct `SourceConfig.auth` from encrypted secrets file
- Initialize `SQLiteEngine` and pre-load all sources marked `cache_1h` or `cache_1d`

**8.2** `packages/connector-runtime/src/cache.ts`:
- TTL cache keyed by `sourceId`
- `get(sourceId)` → data or `undefined` if expired
- `set(sourceId, data, ttl)`
- `invalidate(sourceId)`

**8.3** `packages/connector-runtime/src/executor.ts`:
- `executeToolCall(toolName, params, context)`:
  1. Find tool in connector
  2. Validate params
  3. Refresh sources (check cache → fetch if expired)
  4. Run SQL
  5. Apply responseShape
  6. Return result + meta

**8.4** `packages/connector-runtime/src/protocols/mcp.ts`:
- HTTP server on `http://localhost:{port}/mcp`
- Handle `initialize`, `tools/list`, `tools/call` JSON-RPC methods
- `tools/list`: return all tools + skills as MCP tool definitions with JSON schema
- `tools/call`: route to `executeToolCall` or `executeSkill`
- Rate limiting: in-memory token bucket per session

**8.5** `packages/connector-runtime/src/protocols/openai.ts`:
- `GET /openai/tools` → OpenAI function-calling schema array
- `POST /openai/call/{toolName}` → execute and return JSON

**8.6** `packages/connector-runtime/src/audit.ts`:
- Append `AuditLogEntry` to `.elliot/audit.ndjson` after every call (async fire-and-forget)
- `readAuditLog(limit)` → parse last N entries

**8.7** `packages/connector-runtime/src/index.ts` — CLI entry (`elliot serve --port 3001 --connector ...`)

**8.8** Write integration tests:
- Load fixture connector → list tools → call tool → check result
- Rate limiting kicks in after burst
- Audit log entries written correctly
- Cache: second call returns same data without re-fetching

### Files Created
```
packages/connector-runtime/src/loader.ts
packages/connector-runtime/src/cache.ts
packages/connector-runtime/src/executor.ts
packages/connector-runtime/src/audit.ts
packages/connector-runtime/src/server.ts
packages/connector-runtime/src/index.ts
packages/connector-runtime/src/protocols/mcp.ts
packages/connector-runtime/src/protocols/openai.ts
packages/connector-runtime/tests/integration/runtime.test.ts
```

### Acceptance Criteria
- Claude Desktop can connect to the runtime and call tools
- Tools return correct data from live sources
- Audit log has an entry for every call
- Cache respects TTL settings from `SourceConfig.refreshStrategy`

---

## Mission 9: Studio — Core UI (Vite + shadcn)
**Estimated**: 12–14 hours | **Dependencies**: Missions 5, 8

### Objective
Build the Elliot Studio React application: dashboard, source browser, tool builder UI, and connector manager.

### Steps

**9.1** Vite + React + TypeScript + Tailwind + shadcn setup (see DEVELOPMENT_GUIDE Section 6)

**9.2** Application shell:
- `AppShell` with collapsible Sidebar
- Sidebar nav: Dashboard, Sources, Tools, Skills, Connector, Playground, Metrics, Evaluation
- Top header with connector status indicator (running / stopped)
- Mobile responsive (sidebar collapses to burger menu)

**9.3** Dashboard page (`/`):
- Stats cards: sources loaded, tools created, skills, connector status
- Getting-started checklist (greyed-out steps, ticked when done)
- Recent audit log feed (last 10 entries from `.elliot/audit.ndjson`)
- Quick-action buttons: "Discover Source", "Create Tool", "Build Connector"

**9.4** Sources page (`/sources`):
- List of sources with table counts and last-fetched timestamp
- "Add Source" form: type selector (API / File / DB), dynamic sub-form per type
- Table browser: expandable table → column list with type badges
- Profile table button → column statistics panel
- Refresh source button

**9.5** Tools page (`/tools`):
- Tool cards: name, category badge, description preview, invocation count
- Tool editor (right panel or drawer):
  - Name, description, category fields
  - SQL editor with syntax highlighting (CodeMirror or Monaco lite)
  - Parameters list with add/remove
  - Response shape config
  - Test runner: input form → result table

**9.6** Skills page (`/skills`):
- Skill list
- Skill builder: step list with drag-to-reorder, input binding editor

**9.7** Connector page (`/connector`):
- Tool/skill selector (checkboxes)
- Deploy button → calls runtime API
- Connection config display with copy buttons (Claude Desktop, OpenAI, REST)

**9.8** `src/lib/api.ts` — fetch wrapper connecting Studio to connector runtime REST API

**9.9** Write unit tests for critical components:
```
ToolCard.test.tsx      — renders correctly, badge shows category
ToolEditor.test.tsx    — form validation, submit calls API
SqlEditor.test.tsx     — validates SQL on change
ParameterRow.test.tsx  — add/remove/edit params
```

### Files Created
```
packages/studio/src/main.tsx
packages/studio/src/App.tsx
packages/studio/src/router.tsx
packages/studio/src/lib/{utils,api,store}.ts
packages/studio/src/components/layout/{AppShell,Sidebar,Header}.tsx
packages/studio/src/pages/{Dashboard,SourcesPage,ToolsPage,SkillsPage,ConnectorPage}.tsx
packages/studio/src/components/{sources,tools,skills,connector}/...
packages/studio/src/tests/unit/...
```

### Acceptance Criteria
- All 7 pages render without errors
- Tool can be created and tested entirely through the Studio UI (no CLI needed)
- Connector can be built and started from the UI
- Connection config snippet can be copied in one click

---

## Mission 10: Studio — Playground & Metrics
**Estimated**: 8–10 hours | **Dependencies**: Mission 9

### Objective
Add the Playground (chat with real agent + tool call inspector) and the Metrics dashboard.

### Steps

**10.1** Playground page (`/playground`):
- Split-pane: chat on left, tool call inspector on right
- Chat input at bottom; streaming AI response display
- Backend: `POST /api/playground/chat` — calls Claude claude-opus-4-7 with connector tools loaded
- When Claude calls a tool: forward to connector runtime, feed result back
- Each tool call → add entry to inspector panel (tool name, params, result, latency)
- Inspector entry click → open tool editor in Sheet
- Export conversation as few-shot prompt example

**10.2** Metrics page (`/metrics`):
- Time series chart: tool calls per day (last 30 days) — `recharts` via shadcn chart
- Tool usage breakdown: bar chart of top tools by call count
- Success rate gauge
- Average latency table by tool
- All data read from `.elliot/audit.ndjson` via connector runtime REST endpoint

**10.3** `packages/connector-runtime/src/protocols/rest.ts`:
- Add REST endpoints the Studio consumes:
  - `GET /studio/connector` — return `ConnectorConfig`
  - `GET /studio/tools` — return tool list with metadata
  - `GET /studio/audit?limit=N` — return last N audit entries
  - `GET /studio/metrics` — aggregated metrics from audit log
  - `POST /studio/playground/chat` — streaming Claude chat with tool use

### Acceptance Criteria
- User can type in Playground and Claude uses their tools in real time
- Every tool call appears in the inspector within 100ms of the call being made
- Metrics page shows accurate data from the audit log
- Conversation export adds a prompt to the prompts list

---

## Mission 11: Evaluation Framework
**Estimated**: 8–10 hours | **Dependencies**: Mission 10

### Objective
Build the evaluation framework: create test suites, run evaluations against the connector, and get a quality score.

### Steps

**11.1** Evaluation page (`/evaluation`):
- Create/edit eval suites (EvalSuite + EvalCase)
- Run evaluation button → execute all cases
- Results view: overall score, case-by-case breakdown, pass/fail per case
- Score history chart: compare runs over time
- Regression alert: cases that passed before but now fail

**11.2** `packages/core/src/evaluation/runner.ts`:
- `runEvalSuite(suite, connector, apiKey)`:
  - For each case: send question to Claude with connector tools
  - Record all tool calls
  - Score against expectedToolCalls
  - Optionally: LLM judge compares answer to expectedFinalAnswer
- Return `EvalRunResult`

**11.3** Description quality analyzer `packages/core/src/evaluation/quality-analyzer.ts`:
- Run `QUALITY_CHECKS` (see ARCHITECTURE.md Section 7.3) against all tools
- Return per-tool quality issues and an overall `ConnectorQualityScore`
- Integrate into the Evaluation page as a "Quick Scan" button

**11.4** Persist eval suites and results to `.elliot/eval/`

**11.5** Write unit tests:
```
quality-analyzer.test.ts:
  - short description fails min_length
  - description not starting with verb fails starts_with_verb
  - jargon ("SQL", "endpoint") fails no_jargon
  - all checks pass for a well-written tool
```

### Acceptance Criteria
- User can create a test suite with 5+ cases
- Running evaluation produces a score and per-case breakdown
- Regression detection flags previously-passing cases that now fail
- Quality analyzer identifies common description issues

---

## Mission 12: Polish, Integration Tests & Documentation
**Estimated**: 8–10 hours | **Dependencies**: All previous

### Objective
Production quality: comprehensive integration tests, error handling, empty states, and documentation.

### Steps

**12.1** End-to-end integration test (in `packages/mcp-plugin/tests/integration/`):
- Full flow: discover CSV source → create tool → build connector → start runtime → call tool via MCP → verify result → check audit log

**12.2** Error handling audit:
- Every `catch` block produces a user-readable `ElliotError` (never a raw `Error.message` to the agent)
- All empty states in Studio have a CTA (no blank pages)
- Network errors in Studio show a toast with retry button
- SQLite `SQLITE_ERROR` surfaces the problematic column name

**12.3** `ElliotError` class:
```typescript
export class ElliotError extends Error {
  constructor(
    public readonly code: string,   // e.g. "INVALID_SQL", "SOURCE_FETCH_FAILED"
    message: string,
    public readonly detail?: unknown,
  ) { super(message); }
}
```
All internal errors map to `ElliotError` before surfacing to MCP responses.

**12.4** Final documentation updates:
- Add `CHANGELOG.md` for Phase 1
- Verify all code examples in DEVELOPMENT_GUIDE.md work
- Add inline JSDoc to all public exported functions

**12.5** CI setup (`.github/workflows/ci.yml`):
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v3
      - uses: actions/setup-node@v4
        with: { node-version: 20, cache: pnpm }
      - run: pnpm install --frozen-lockfile
      - run: pnpm typecheck
      - run: pnpm test:coverage
```

### Acceptance Criteria
- Full E2E integration test passes in CI
- All packages hit 85% line coverage
- Zero TypeScript errors
- All Studio pages have non-empty empty states
- CI green on a fresh clone

---

## Mission Summary

| # | Mission | Hours | Key Deliverable |
|---|---|---|---|
| 1 | Monorepo Foundation | 3–4 | pnpm + TS + Vitest workspace |
| 2 | JSON Flattener | 10–12 | Core engine + 15+ tests |
| 3 | SQLite Engine | 6–8 | In-memory DB + safe query runner |
| 4 | Source Fetchers | 10–12 | API + file + DB fetchers |
| 5 | Tool Registry & Executor | 8–10 | Tool + skill execution |
| 6 | MCP Plugin: Sources & SQL | 8–10 | Claude Code can discover APIs |
| 7 | MCP Plugin: Tools & Connector | 6–8 | Claude Code builds full connector |
| 8 | Connector Runtime | 10–12 | `elliot serve` MCP server |
| 9 | Studio Core UI | 12–14 | Dashboard + tools + sources |
| 10 | Playground & Metrics | 8–10 | Chat UI + analytics |
| 11 | Evaluation Framework | 8–10 | Quality scoring + eval suites |
| 12 | Polish & CI | 8–10 | E2E tests + CI green |

**Total**: 97–122 hours

### Critical Path

**1 → 2 → 3 → 4 → 5** (core library, must be sequential)
**then → 6 → 7** (MCP plugin, uses core)
**and → 8** (runtime, uses core, can run in parallel with 6-7)
**then → 9 → 10 → 11** (studio, uses runtime)
**then → 12** (polish everything)
