---
name: getting-started
description: Master onboarding for Elliot. Read this first when you connect to Elliot — and ALSO read this when any Elliot tool call fails with a connection error, because the most likely cause is the Elliot server isn't running yet. Explains how to start Elliot, the five principles, the canonical workflow, and which Elliot prompts and tools to call for each task.
when_to_use: Trigger on first connection to Elliot, when any Elliot tool returns a connection-refused / transport error, or when the user says "what is Elliot", "how do I use Elliot", "get started", "elliot not working", "can't connect to elliot", or similar. Re-read when uncertain which Elliot prompt to invoke next.
argument-hint: ""
allowed-tools: Bash mcp__elliot__*
---

# Elliot — Getting Started

You are working with **Elliot**, a platform that turns existing APIs and databases into **agent-ready MCP connectors**. Your job is to help the user design, validate, deploy, and observe agent-ready tool sets built around their data sources.

## ⚠️ PREREQUISITE — is the Elliot server actually running?

Elliot is a local service. The MCP plugin URL (`http://localhost:3000/mcp/`) won't respond unless the user has the Elliot stack running. **Always check this first** — most "Elliot isn't working" problems are just the server not being up.

### Quick check

Try calling `elliot_get_session_state`. Three possible outcomes:

| Outcome | What it means | What to do |
|---|---|---|
| Returns a result with counts | Server is running ✓ | Skip to the workflow section below |
| MCP transport error / connection refused | Server isn't running | Walk the user through starting it (next section) |
| `tools/list` doesn't include any `elliot_*` tools | Plugin isn't installed at all | Tell the user to run `/plugin install elliot@elliot` first |

`elliot_get_session_state` returns counts of sources / tools / skills plus
`connector_built` and `runtime_running` — it's the canonical "what's in this
session" probe. (`elliot_session_summary` and `studio_get_connector_info` exist
as thinner / Studio-flavoured variants of the same idea.)

### If the server isn't running, tell the user

Stop and ask the user to start Elliot. Use this exact message:

> "I can't reach the Elliot server. It needs to be running locally on `http://localhost:3000` before I can use any of its tools. Please open a terminal and run:
>
> ```
> git clone https://github.com/EliBarak12/Elliot.git
> cd Elliot
> make setup     # one-time: installs uv + pnpm deps
> make dev       # starts plugin (3000) and studio (5173)
> ```
>
> Once it's running, Studio will open automatically in your browser at `http://localhost:5173`. Tell me when you see it and I'll continue."

**Do not retry tool calls in a loop while waiting.** Wait for the user to confirm Elliot is up, then re-run `elliot_session_summary`.

### If the user already has Elliot installed and just needs to start it

If the user says "I have Elliot already" or you see `.elliot/` or a `Makefile` with `dev:` in their cwd, give the short version:

> "Run `make dev` from the Elliot repo to start the stack. Studio will open in your browser when it's ready."

## The five principles

Every Elliot tool you create or modify must honor these:

1. **Tool descriptions are contracts** — verb-first, unambiguous, typed.
2. **Results are sized for context windows** — never raw table dumps; paginate, project, summarize.
3. **Errors are actionable** — every error must tell the agent what to do next.
4. **Every agent session is observable** — token cost, latency, and errors are all surfaced in Studio.
5. **The platform itself is agentic** — you (the agent) build connectors *through* Elliot, not for it.

## Discovery: what's available right now

Call these any time you need to refresh what's available:

- `prompts/list` — every workflow Elliot ships (getting-started, onboard-product, discover-source, build-connector, lint-connector, run-eval, audit-connector, deploy, observe-agent-runs, compose-skill).
- `resources/list` — connector templates, error reference, principles, install instructions.
- `tools/list` — the Elliot MCP tools (all prefixed `elliot_`).

## Canonical workflow

When the user wants to build a new connector, follow this exact order. Each numbered step has a dedicated Elliot prompt — invoke it via `prompts/get`.

| # | Prompt | What it does |
|---|--------|--------------|
| 1 | `discover-source` | Identify the user's data source (REST API, Postgres, etc.) and call `elliot_set_context` + `elliot_discover_source` |
| 2 | `build-connector` | Create tools (`elliot_create_tool`), then `elliot_build_connector` to assemble them into a connector |
| 3 | `lint-connector` | Run `elliot_lint_connector` on the built connector; fix every error and warning |
| 4 | `run-eval`        | Run `elliot_run_eval` to validate tool quality against expected outputs |
| 5 | `audit-connector` | Spawn parallel sub-agents to exercise the connector for real, then fix what they break |
| 6 | `deploy`          | Full pipeline: build → lint → eval → `elliot_export_connector` → `elliot_start_runtime` |

If the user is somewhere mid-workflow, jump straight to the right prompt. Don't start from step 1 every time.

## Reference resources you should know about

These are accessible via `resources/read`:

- `elliot://docs/principles` — the five principles in full.
- `elliot://docs/error-codes` — every `ElliotError` code and how to recover.
- `elliot://templates/rest-api-key` — starter REST API connector with bearer/key auth.
- `elliot://templates/postgres-readonly` — starter Postgres read-only connector.
- `elliot://templates/paginated-rest` — REST API with cursor/offset pagination.
- `elliot://templates/openapi-petstore` — full Petstore example.
- `elliot://docs/install` — how a new user wires Elliot into their own agent.

## What you must NEVER do

- Never log secret values, API keys, or raw query results — they may contain PII.
- Never call `elliot_export_connector` before `elliot_build_connector`, lint, and eval all pass.
- Never invent tool annotations — `readOnlyHint`, `destructiveHint`, `openWorldHint` must be set deliberately, because the user's downstream agents rely on them to decide whether to confirm before calling.
- Never use a tool the user hasn't asked for (e.g. don't run `elliot_start_runtime` unless the user is ready to deploy).

## Your first move

If this is the user's first message: ask them what API or database they want to turn into agent tools. If they give you a URL or a connection-string shape, immediately call `prompts/get name=discover-source` and proceed from there.

If the user says "show me Elliot", call `elliot_session_summary` and `prompts/list` so they can see the full surface at a glance.
