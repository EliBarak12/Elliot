> **Note:** This specification was written before the Python rewrite. The product vision, phases, and user stories are unchanged. The implementation language for backend services is now **Python 3.12** (not TypeScript). See [`README.md`](../README.md) for the current tech stack.

---

# Elliot — Product Specification

## Vision

Every product that has an API or a database should be able to become AI-native in under an hour — without rewriting application code, adding a vendor SDK, or managing a cloud service.

Elliot is the bridge: a local, open-source connector platform that translates your existing data interfaces into MCP tools that any AI coding agent can discover and call.

---

## Phases

### Phase 1 — Local Connector (current)

**Goal**: Developer can take any REST API or database and expose it as MCP tools to Claude Code in under an hour.

**Deliverables**:
- `elliot-core` — Python library: Pydantic types, SQLite engine, JSON flattener, auth helpers
- `elliot-mcp-plugin` — FastMCP server on :3000, loads connectors, registers tools
- `elliot-connector-runtime` — FastAPI server on :3001, executes tools against live data
- `elliot-studio` — React dashboard to browse, test, and monitor connectors
- `.connector.json` schema + CLI validator

**Success criteria**:
- A developer with an existing REST API can produce a working connector in < 60 minutes
- Claude Code can discover and call tools without any custom code
- Audit log captures every tool call with timing

### Phase 2 — Connector Registry (planned)

- Shareable connector catalogue (public + private)
- One-command install: `elliot add stripe`
- Version pinning and update notifications

### Phase 3 — Cloud Runtime (planned)

- Hosted connector runtime (no local process needed)
- OAuth flow for third-party API auth
- Multi-tenant isolation
- Usage analytics dashboard

---

## User Stories

### S-01: Connect a REST API
> As a backend developer, I want to write a `.connector.json` for our internal API so that Claude Code can query our data without me writing any glue code.

**Acceptance**: Claude Code tool list includes my defined tools; calling a tool returns live rows.

### S-02: Filter with parameters
> As a developer, I want to define tool parameters (e.g. `species: string`) so that Claude Code can pass arguments and get filtered results.

**Acceptance**: SQL `:param` binding works; extra parameters are ignored; missing required params return a validation error.

### S-03: Test a tool in Studio
> As a developer, I want to open Elliot Studio and run a tool manually so I can verify it returns the right data before giving it to Claude.

**Acceptance**: Studio Playground page lets me select a tool, fill in parameters, and see the result table with timing.

### S-04: Monitor tool usage
> As a developer, I want to see a log of every tool call — which tool, what args, how many rows, how long it took — so I can debug issues.

**Acceptance**: Studio Metrics page shows the audit log; each entry has tool_id, arguments, result_row_count, duration_ms.

### S-05: Secure credentials
> As a developer, I want API keys and DB passwords to live in environment variables, not in the connector file, so I can safely commit the file to git.

**Acceptance**: `auth.secret_key` is a key name resolved at runtime from env or secrets file; connector file contains no secrets.

### S-06: Hot-reload connector changes
> As a developer, I want changes to my `.connector.json` to be picked up automatically so I don’t have to restart the server during development.

**Acceptance**: ConnectorCache detects mtime change within 30 seconds; next tool call uses the updated connector.

---

## KPIs (Phase 1)

| Metric | Target |
|---|---|
| Time to first working connector | < 60 minutes |
| Tool call latency (REST source, p95) | < 2 seconds |
| Test coverage — `elliot-core` | ≥ 95% |
| Test coverage — `elliot-connector-runtime` | ≥ 85% |
| Audit log write failure rate | 0% |
