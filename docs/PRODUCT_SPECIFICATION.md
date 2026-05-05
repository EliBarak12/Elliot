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

## KPIs (Phase 1)

| Metric | Target |
|---|---|
| Time to first working connector | < 60 minutes |
| Tool call latency (REST source, p95) | < 2 seconds |
| Test coverage — `elliot-core` | ≥ 95% |
| Test coverage — `elliot-connector-runtime` | ≥ 85% |
| Audit log write failure rate | 0% |
