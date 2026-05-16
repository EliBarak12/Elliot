<div align="center">

<img src="website/public/logo-mark.svg" alt="Elliot" width="96" height="96" />

# Elliot

**Turn any API or database into MCP tools for Claude, Cursor, and Codex — with built-in observability.**

[![CI](https://github.com/EliBarak12/Elliot/actions/workflows/ci.yml/badge.svg)](https://github.com/EliBarak12/Elliot/actions/workflows/ci.yml)
[![Docs](https://github.com/EliBarak12/Elliot/actions/workflows/docs.yml/badge.svg)](https://github.com/EliBarak12/Elliot/actions/workflows/docs.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-success.svg)](LICENSE)
[![MCP compatible](https://img.shields.io/badge/MCP-compatible-00cec8)](https://modelcontextprotocol.io)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776ab.svg?logo=python&logoColor=white)](pyproject.toml)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CLAUDE.md#before-every-push--mandatory-checks)

**[Docs](https://elibarak12.github.io/Elliot/)** · **[Quickstart](https://elibarak12.github.io/Elliot/docs/quickstart)** · **[The five principles](https://elibarak12.github.io/Elliot/docs/five-principles)** · **[Agent Experience (AX)](https://elibarak12.github.io/Elliot/docs/ax-principles)**

</div>

---

Elliot is the interface layer that makes your product feel native to AI agents. Design, validate, deploy, and observe agent-ready tools built around your existing APIs, databases, and files — with **minimum tokens, clean error recovery, and full observability** of every session.

> **AX** is to agents what UX is to users and DX is to developers. Elliot's job is to make AX measurable.

## 60-second quickstart

```bash
git clone https://github.com/EliBarak12/Elliot.git && cd Elliot
make setup
make dev          # boots plugin (:3000) + runtime (:3001) + studio (:5173)
                  # and writes the MCP config for every detected coding agent
```

That's it. Open Studio at <http://localhost:5173>, scaffold a connector, lint it, and your agent can use it in the same session.

## Install for your agent

`make dev` runs `elliot connect`, which detects every coding agent on your machine and writes the MCP config for each. If you'd rather wire one client manually:

<table>
<tr><th>Claude Code</th><th>Cursor</th></tr>
<tr><td>

```
/plugin marketplace add EliBarak12/Elliot
/plugin install elliot@elliot
```

</td><td>

Add to your Cursor MCP config:
```json
{ "mcpServers": { "elliot": {
  "url": "http://localhost:3000/mcp/"
}}}
```

</td></tr>
<tr><th>Codex</th><th>OpenClaw</th></tr>
<tr><td>

```
codex plugin marketplace add EliBarak12/Elliot
/plugin install elliot
```

</td><td>

Pointed to `http://localhost:3000/mcp/` by `elliot connect`, which writes `~/.openclaw/openclaw.json` with the `streamable-http` transport.

</td></tr>
</table>

Every install path wires the MCP URL only — Elliot's server still needs to be running (`make dev` locally, or a hosted endpoint).

## Why Elliot

Connecting an API to Claude is easy. Making it work *well* with agents is not. Agents fail when:

- **Tool descriptions are vague** → the agent picks the wrong tool
- **Results are too large** → context window fills up before the answer
- **Errors are unstructured** → the agent can't recover or escalate
- **No observability** → you don't know it's broken until a user complains

Elliot makes these visible and fixable. Every tool ships with a structured schema, a token estimate, an actionable error shape, and a session trace — every call, every agent, with the client and model attributed.

## How it works

```
1. Connect your data sources
   └ REST APIs, PostgreSQL, MySQL, CSV / JSON files — all in one connector
   └ Local files: agents call elliot_upload_file then elliot_discover_source

2. Build tools (no SQL required)
   └ Define name, description, parameters, filter conditions, return fields
   └ Elliot generates safe parameterised queries
   └ Or: let an AI agent build the connector for you via the agentic builder

3. Lint for agent-readiness
   └ elliot lint my-domain.connector.json

4. Write and run eval cases
   └ elliot eval my-domain.eval.yaml → pass/fail + token estimate

5. Deploy and connect agents
   └ elliot-mcp-plugin (:3000) — Claude Code / any MCP client
   └ elliot-connector-runtime (:3001) — live data, session logs
   └ elliot-studio (:5173) — observe, run, edit
```

## What the agent gets on first connect

Whatever install path you use, the agent's first action on connect is to call `prompts/get name=getting_started`. That one prompt teaches the [five principles](https://elibarak12.github.io/Elliot/docs/five-principles), the canonical workflow (`discover-source` → `build-connector` → `lint-connector` → `run-eval` → `deploy`), and the available reference resources (templates, error-code dictionary, install docs).

## Local dev

```bash
# Prerequisites: uv (Python 3.13), pnpm (Node 22)
curl -LsSf https://astral.sh/uv/install.sh | sh
npm install -g pnpm

git clone https://github.com/EliBarak12/Elliot.git && cd Elliot
make setup
cp .env.example .env
make dev              # or: honcho start (skips auto-register)

elliot status
elliot init --template rest-api-key my-api.connector.json
elliot lint my-api.connector.json
elliot eval my-api.eval.yaml
```

## Repository structure

```
elliot/
├── packages/
│   ├── core/              elliot-core          types, query builder, linter, eval
│   ├── mcp-plugin/        elliot-mcp-plugin    MCP + FastAPI :3000
│   ├── connector-runtime/ elliot-connector-runtime  runtime :3001 + session tracker
│   └── studio/            elliot-studio        React 19 + Vite :5173
├── connectors/        your .connector.json files
├── templates/         starter connectors
├── Procfile           honcho dev runner
├── docker-compose.yml production
└── .env.example       all env vars documented
```

## Tech stack

| Layer | Language | Key libraries |
|---|---|---|
| Core library | Python 3.13 | `pydantic`, `sqlite3`, `httpx`, `sqlalchemy` |
| MCP plugin | Python 3.13 | `mcp` (FastMCP), `fastapi`, `uvicorn`, `structlog` |
| Connector runtime | Python 3.13 | `mcp` (FastMCP), `fastapi`, `uvicorn`, `slowapi`, `pymysql` |
| Studio UI | TypeScript | React 19, Vite, shadcn/ui, TanStack Router/Query/Table, Zustand v5 |
| Package managers | `uv` (Python) · `pnpm` (Node 22) | |

## Key ports

| Service | Port | Purpose |
|---|---|---|
| `elliot-mcp-plugin` | 3000 | MCP endpoint for agents + agentic builder tools |
| `elliot-connector-runtime` | 3001 | Tool execution, session tracking, observation store |
| `elliot-studio` | 5173 | Visual dashboard — sessions, tools, metrics, editor |

## Contributing

PRs welcome. Good first issues are labelled [`good first issue`](https://github.com/EliBarak12/Elliot/issues?q=is%3Aopen+label%3A%22good+first+issue%22). Before pushing, run the [mandatory checks](CLAUDE.md#before-every-push--mandatory-checks). New connectors are especially valuable — see the [connector request template](.github/ISSUE_TEMPLATE/connector_request.yml).

## License

[MIT](LICENSE)
