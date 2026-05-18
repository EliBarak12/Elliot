# Changelog

All notable changes to Elliot are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- DB filter push-down: when a connector tool's filters compile to a `SELECT` (filter_groups / return_fields, no raw SQL) and it targets a single Postgres/MySQL source, the connector runtime now runs that `SELECT` — `WHERE`, projection, `ORDER BY`, `LIMIT` — directly against the database instead of fetching the whole table into the in-memory SQLite mirror. The agent's parameters reach the real query and large tables no longer cross the wire. Raw-SQL and multi-source tools keep the SQLite-snapshot path. `build_select_sql` gained `dialect` / `from_clause` parameters and `elliot_core.sources.db_connector` gained `run_select`.
- Agent Experience (AX) docs page mapping Elliot to the broader AX principles (`website/docs/ax-principles.md`).
- Structured agent identity capture: `AgentIdentity` parser + ASGI `AgentIdentityMiddleware` extract the AX `User-Agent` convention (`agent-<tool>[/<version>] [model-<id>]`) and common MCP client UA strings into a request-scoped contextvar. Session NDJSON and the `agent_sessions` table now carry `client`, `client_version`, `model`, `modality`, and the raw `user_agent`. Studio renders these as badges in the Agent Console.
- Opt-in confirmation gate for destructive tools: when `ELLIOT_REQUIRE_DESTRUCTIVE_CONFIRMATION=true`, every `WRITE`/`ACTION` tool gains a required `confirm: bool` parameter and returns a structured `CONFIRMATION_REQUIRED` error if called without it.
- GitHub issue templates for bug reports, feature requests, and connector requests.

### Changed
- The connector runtime's DB fetch path now goes through elliot-core's SQLAlchemy connector. MySQL sources work in the runtime (they were previously routed through the Postgres-only `psycopg2` driver), Postgres runs in a read-only transaction, and a source's custom `query` is validated as a single read-only `SELECT` before it runs.
- README hero rewritten around the agent-first value proposition with badges, a 60-second quickstart, and per-client install snippets.

## [0.1.0] — Unreleased

The first tagged release captures the foundation of Elliot:

- `elliot-core` — type system, query builder, linter, eval runner, secrets, redaction.
- `elliot-mcp-plugin` (port 3000) — MCP server exposing the agentic builder (`discover-source`, `build-connector`, `lint-connector`, `run-eval`, `deploy-connector`) plus skills surfaced as MCP prompts and resources.
- `elliot-connector-runtime` (port 3001) — FastAPI + FastMCP tool execution, session tracker, observation store (SQLite default / MySQL optional), OpenAI-protocol bridge, OpenTelemetry export.
- `elliot-studio` (port 5173) — React 19 + Vite UI for designing connectors, running tools, viewing session traces, and watching token-efficiency metrics.
- Marketplace install for Claude Code and Codex via `.claude-plugin/marketplace.json` and `.codex-plugin/`.
- Five-principles linter and per-tool eval suites with token-cost gates.

[Unreleased]: https://github.com/EliBarak12/Elliot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/EliBarak12/Elliot/releases/tag/v0.1.0
