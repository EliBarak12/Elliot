<div align="center">

<img src="website/public/logo-mark.svg" alt="Elliot" width="96" height="96" />

# Elliot

**Turn any API or database into MCP tools for Claude, Cursor, and Codex — with built-in observability.**

[![CI](https://github.com/EliBarak12/Elliot/actions/workflows/ci.yml/badge.svg)](https://github.com/EliBarak12/Elliot/actions/workflows/ci.yml)
[![Docs](https://github.com/EliBarak12/Elliot/actions/workflows/docs.yml/badge.svg)](https://github.com/EliBarak12/Elliot/actions/workflows/docs.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-success.svg)](LICENSE)
[![MCP compatible](https://img.shields.io/badge/MCP-compatible-00cec8)](https://modelcontextprotocol.io)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776ab.svg?logo=python&logoColor=white)](pyproject.toml)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#contributing)

[**Documentation**](https://elibarak12.github.io/Elliot/) · [**Quickstart**](https://elibarak12.github.io/Elliot/docs/quickstart) · [**Concepts**](https://elibarak12.github.io/Elliot/docs/concepts) · [**The five principles**](https://elibarak12.github.io/Elliot/docs/five-principles)

</div>

---

Elliot is an open-source platform for turning the products you already have — REST APIs, SQL databases, files — into tools that AI agents can use *well*. Not just connected, but **fast, safe, and observable**: minimal token usage, structured errors the agent can recover from, and a full trace of every agent session.

> **AX** is to agents what UX is to users and DX is to developers. Elliot's job is to make AX measurable.

## Features

- 🧭 **Agent-ready by design** — every tool is linted against five concrete principles before it ships: verb-first descriptions, typed parameters, context-sized results.
- 🛡️ **Safe by default** — parameterised SQL, env-var secrets, no keys in connector files. Connector files are safe to commit.
- 🔭 **Every call observable** — tokens, latency, arguments, and errors for every agent call, streamed to an audit log and visible in Studio.
- ⚙️ **One command to run** — start the whole stack with Docker. No Python, Node, or toolchain to install.
- 🧩 **Works with every agent** — Claude Code, Cursor, Codex, OpenClaw, VS Code Copilot, Windsurf. Elliot auto-registers with each.
- 🤖 **Agents build connectors** — `discover → build → lint → eval → deploy`. The platform itself is agentic: agents can build connectors through Elliot.

## Quickstart

**Just want to run Elliot?** The only prerequisite is [Docker](https://docs.docker.com/get-docker/) — no Python, Node, `uv`, or `pnpm`:

```bash
curl -LsSf https://raw.githubusercontent.com/EliBarak12/Elliot/main/scripts/install.sh | sh
```

This pulls the pre-built images, generates a local `.env`, starts all three services, and opens **Studio** at <http://localhost:8080>. Stop it any time with `docker compose -f docker-compose.run.yml down`.

**Want to develop Elliot?** Build from source instead:

```bash
# Prerequisites: uv (Python 3.13) and pnpm (Node 22)
git clone https://github.com/EliBarak12/Elliot.git && cd Elliot
make setup
make dev          # boots plugin (:3000) + runtime (:3001) + studio (:5173)
                  # and writes the MCP config for every detected coding agent
```

Then open Studio at <http://localhost:5173>, scaffold a connector, lint it, and your agent can use it in the same session.

## Connect your coding agent

`make dev` runs `elliot connect`, which detects every coding agent on your machine and writes its MCP config automatically. To wire a client by hand:

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

Pointed at `http://localhost:3000/mcp/` by `elliot connect`, which writes `~/.openclaw/openclaw.json` with the `streamable-http` transport.

</td></tr>
</table>

Every install path wires the MCP URL only — Elliot's server still needs to be running (locally, or at a hosted endpoint).

## Why Elliot

Connecting an API to an agent is easy. Making it work *well* is not. Agents fail when:

- **Tool descriptions are vague** → the agent picks the wrong tool.
- **Results are too large** → the context window fills up before the answer does.
- **Errors are unstructured** → the agent can't recover or escalate.
- **Nothing is observable** → you don't find out it's broken until a user complains.

Elliot makes each of these visible and fixable. Every tool ships with a structured schema, a token estimate, an actionable error shape, and a session trace — every call, every agent, attributed to a client and model.

## How it works

```
1. Connect your data sources
   └ REST APIs, PostgreSQL, MySQL, CSV / JSON files — all in one connector

2. Build tools (no SQL required)
   └ Define name, description, parameters, filters, and return fields
   └ Elliot generates safe, parameterised queries
   └ Or let an agent build the connector for you with the agentic builder

3. Lint for agent-readiness
   └ elliot lint my-domain.connector.json

4. Write and run eval cases
   └ elliot eval my-domain.eval.yaml → pass/fail + token estimate

5. Deploy and connect agents
   └ plugin (:3000) serves tools to any MCP client
   └ runtime (:3001) executes them against live data
   └ studio observes, runs, and edits everything
```

On first connect, an agent automatically calls `prompts/get name=getting_started` — a single prompt that teaches it the five principles, the canonical workflow, and the reference resources available (templates, error-code dictionary, install docs).

## Documentation

Full documentation lives at **[elibarak12.github.io/Elliot](https://elibarak12.github.io/Elliot/)**.

- [Quickstart](https://elibarak12.github.io/Elliot/docs/quickstart) — get a connector running in minutes
- [Concepts](https://elibarak12.github.io/Elliot/docs/concepts) — sources, tools, skills, connectors
- [The five principles](https://elibarak12.github.io/Elliot/docs/five-principles) — the design rules every connector follows
- [Connector spec](https://elibarak12.github.io/Elliot/docs/connectors) — the full `.connector.json` schema
- [Architecture](https://elibarak12.github.io/Elliot/docs/architecture) — how the three services fit together
- [Deployment](https://elibarak12.github.io/Elliot/docs/deployment) — Docker images, env vars, hosting

## Project layout

Elliot is a monorepo of four packages:

| Package | Name | Stack | Role |
|---|---|---|---|
| `packages/core` | `elliot-core` | Python 3.13 | Types, query builder, linter, eval harness, CLI |
| `packages/mcp-plugin` | `elliot-mcp-plugin` | Python 3.13 · FastMCP | MCP endpoint + agentic builder — port `3000` |
| `packages/connector-runtime` | `elliot-connector-runtime` | Python 3.13 · FastAPI | Tool execution + session/observation store — port `3001` |
| `packages/studio` | `elliot-studio` | React 19 · Vite | Visual dashboard — port `5173` (dev) / `8080` (Docker) |

Connector files live in `connectors/`, starter templates in `templates/`, and every environment variable is documented in [`.env.example`](.env.example).

## Roadmap

Elliot's goal is to be usable by everyone, not just developers. Progress is tracked in [`docs/USER_ONBOARDING.md`](docs/USER_ONBOARDING.md).

- ✅ **Run from source** — `make dev` for contributors
- ✅ **One-command Docker** — run with only Docker, no toolchain
- 🔜 **Guided first-run** — an onboarding wizard inside Studio
- 🧭 **Desktop app** — a double-click app, no Docker, no terminal
- ☁️ **Hosted cloud** — a connector registry and a managed runtime, no install at all

## Contributing

Contributions are welcome — code, connectors, docs, and bug reports alike.

- Browse [good first issues](https://github.com/EliBarak12/Elliot/issues?q=is%3Aopen+label%3A%22good+first+issue%22) to get started.
- New connectors are especially valuable — see the [connector request template](.github/ISSUE_TEMPLATE/connector_request.yml).
- Before opening a PR, run the mandatory checks below. All six must pass.

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/core/src packages/mcp-plugin/src packages/connector-runtime/src
uv run pytest --tb=short
pnpm --filter @elliot/studio run typecheck
pnpm --filter @elliot/studio test --run
```

## Community & support

Found a bug, have a feature request, or want to propose a connector? Open an issue on the [issue tracker](https://github.com/EliBarak12/Elliot/issues) — we read every one.

## License

Elliot is released under the [MIT License](LICENSE).
