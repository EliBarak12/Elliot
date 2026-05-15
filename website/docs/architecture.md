# Architecture

Elliot is three small Python/TypeScript services that share one contract: a connector file.

```
┌─────────────┐     MCP / HTTP     ┌──────────────────────────┐     HTTP / SQL    ┌──────────────┐
│   AGENT     │ ─────────────────▶ │  elliot-mcp-plugin :3000 │ ◀───────────────▶ │   SOURCES    │
│ Claude Code │                    │  FastMCP · tool registry │                   │ REST · PG    │
│  Cursor     │                    └────────────┬─────────────┘                   │ MySQL · CSV  │
│  Codex      │                                 │                                 │  local files │
└─────────────┘                                 ▼                                 └──────────────┘
                                  ┌──────────────────────────┐
                                  │ connector-runtime  :3001 │
                                  │ safe SQL · session log   │
                                  └────────────┬─────────────┘
                                               ▼
                                  ┌──────────────────────────┐
                                  │   elliot-studio    :5173 │
                                  │   observe · run · edit   │
                                  └──────────────────────────┘
                                               │
                                               ▼
                              NDJSON audit log of every call
```

## elliot-mcp-plugin (`:3000`)

A FastMCP server (Streamable HTTP transport) that exposes:

- `tools/list`, `tools/call` — the user-defined tools from every loaded connector
- `prompts/list`, `prompts/get` — skills + the canonical `getting_started` prompt
- `resources/list`, `resources/read` — templates, error-code dictionary, install docs
- A set of platform tools: `elliot_upload_file`, `elliot_discover_source`, `build-connector`, `lint-connector`, `run-eval`, `deploy-connector`

This is the only endpoint any agent talks to.

## elliot-connector-runtime (`:3001`)

The execution engine. When the plugin forwards `tools/call`, the runtime:

1. Materialises the requested sources into an ephemeral in-memory SQLite database
2. Binds parameters and executes the connector's SQL (never string-interpolated)
3. Streams rows back, paginated and projected per the connector spec
4. Writes one NDJSON line to the audit log: `{ts, tool, args, rows, bytes, duration_ms, error, session_id}`

A 30-second TTL + mtime cache hot-reloads connector files without restart.

## elliot-studio (`:5173`)

A React 19 + Vite SPA. Reads from the same audit log and runtime API. Pages:

| Page | Purpose |
|---|---|
| Dashboard | Sources list, auth status, row preview |
| Tools | Per-tool detail, parameter form, SQL viewer, run |
| Skills | Prompt template preview, tool dependencies |
| Playground | Run any tool/skill, raw JSON / table toggle |
| Metrics | Audit log with filter + CSV export |

## How a single call flows

1. Agent calls `tools/call` on `:3000` with `{ name: "list_animals", arguments: { species: "cat" } }`
2. Plugin validates the tool exists and the arguments match the parameter schema
3. Plugin forwards to runtime on `:3001`
4. Runtime fetches `animals` source (cache or live)
5. Runtime runs `SELECT * FROM animals WHERE :species IS NULL OR species = :species` with bound `species="cat"`
6. Runtime returns rows + writes audit line
7. Plugin streams MCP `tools/call` response back to agent
8. Studio shows the call within ~1 second

Total moving parts: three services, one log, one contract.

## Why ephemeral in-memory SQLite?

- No persistent state — every call is fresh
- One SQL engine across heterogeneous sources (REST + Postgres + CSV in one query)
- Cheap to spin up — fewer than 5 ms for typical sources
- Safe — destroying state between calls is the default, not an opt-in

## Why NDJSON audit?

- Greppable on disk (`grep tool=list_animals audit.log | tail -n100`)
- Streamable into any log tool (Loki, Datadog, ELK)
- One line per call, no parser ambiguity
