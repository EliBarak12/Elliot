# Quickstart

Get a connector running and talking to an agent in under five minutes.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) (Python 3.13)
- [`pnpm`](https://pnpm.io/) (Node 22)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
npm install -g pnpm
```

## 1. Clone & install

```bash
git clone https://github.com/EliBarak12/Elliot.git
cd Elliot
make setup
cp .env.example .env
```

## 2. Boot the stack

```bash
make dev
```

`make dev` runs `elliot connect` first — auto-registering Elliot with every coding agent it can find (Claude Code, Cursor, VS Code Copilot, Windsurf, Codex). Then it brings up:

- `elliot-mcp-plugin` on `:3000` (MCP endpoint)
- `elliot-connector-runtime` on `:3001` (tool execution)
- `elliot-studio` on `:5173` (dashboard)

Open <http://localhost:5173>.

## 3. Scaffold your first connector

```bash
elliot init --template rest-api-key my-api.connector.json
```

Open the file. Fill in the source URL, the auth secret name (an env var), and any tools you want exposed. See [Connector spec](./connectors) for the full schema.

## 4. Lint & eval before shipping

```bash
elliot lint my-api.connector.json
elliot eval my-api.eval.yaml
```

The linter checks every tool against the [five principles](./five-principles). The eval harness runs real prompts through real agents and reports a pass/fail with token counts.

## 5. Call a tool from an agent

In Claude Code (or any registered MCP client), ask it a question that needs your data. The agent calls `list_animals` (or whatever you defined), Elliot returns a small, contextually-sized response, and Studio shows the call in the audit log.

## What an agent gets on first connect

On first connect the agent automatically calls `prompts/get name=getting_started`. That single prompt teaches the agent the five principles, the canonical workflow (`discover-source → build-connector → lint-connector → run-eval → deploy`), and the reference resources available (templates, error-code dictionary, install docs).

## Next steps

- [Concepts](./concepts) — sources, tools, skills, connectors
- [The five principles](./five-principles) — the design rules
- [Architecture](./architecture) — how the three services fit together
