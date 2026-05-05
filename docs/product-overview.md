# Elliot — Product Overview

## What is Elliot?

Elliot is a **connector platform** that turns any REST API or database into a set of MCP (Model Context Protocol) tools that AI coding agents (Claude Code, Codex, etc.) can call directly.

A developer writes a single `.connector.json` file describing their data sources and the SQL queries they want to expose as tools. Elliot does the rest: schema generation, HTTP fetching, SQL execution, auth, and audit logging.

---

## Studio Pages & Navigation

- **Dashboard** — Sources overview, getting-started checklist
- **Sources** — Manage loaded sources, add/remove/refresh
- **Tools** — Browse, create, edit, and test tools
- **Skills** — Chain tools into multi-step workflows
- **Connector** — Assemble and export the connector
- **Playground** — Manual tool invocation UI
- **Metrics** — Audit log viewer and token efficiency
- **Agent Console** — Real-time agent session viewer
- **Evaluation** — Eval suite runner and quality scanner

---

## Key Design Decisions

| Decision | Choice | Why |
|---|---|---|
| MCP transport | StreamableHTTP | Works with Claude Code out of the box; no stdio process needed |
| Query engine | Ephemeral in-memory SQLite | No persistent state; each call is fresh |
| Cache strategy | TTL + mtime | Hot-reload without restart; 30s TTL catches most changes |
| Audit format | NDJSON | Greppable, streamable, importable into any log tool |
| Auth secrets | Env vars / secrets file | Never stored in connector.json; safe to commit connector definitions |
| Studio stack | React + Vite + Zustand | Fast dev, minimal boilerplate, easy MCP client integration |
