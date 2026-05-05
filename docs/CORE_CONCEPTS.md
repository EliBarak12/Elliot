> **Note:** The domain concepts in this document are language-agnostic and remain valid.
> The implementation language changed from TypeScript to **Python** for all backend services.
> See [`docs/architecture.md`](architecture.md) for the current technology stack and package layout.

---

# Elliot — Core Concepts

## The Domain Model

```
Product ──► Connector ──► Sources + Tools + Skills
```

**Product** — The existing software system you are building a connector for (a SaaS API, an internal database, a file export).

**Connector** — A versioned `.connector.json` file that describes how to reach the product's data and what operations to expose as AI tools. One file per product integration.

**Source** — A live data origin: a REST endpoint, a PostgreSQL table, a MySQL query, or a file. Each source has an `id` that becomes a SQL table name inside the in-memory SQLite engine.

**Tool** — A named, parameterised SQL query over one or more sources. Tools are what AI agents actually call. They have:
- `id` — machine name (snake_case), used as the MCP tool name
- `name` / `description` — shown to the AI agent
- `category` — `READ` | `WRITE` | `ACTION`
- `sql` — the query to run (`:param` placeholders)
- `parameters` — typed, required/optional inputs

**Skill** — A higher-level operation that chains multiple tools together with a prompt template. Skills are the building blocks for AI workflows (e.g. "animal population report" = call `list_animals` + summarise with a prompt).

**Auth** — Per-source authentication config (`api_key`, `bearer`, `basic`). Secret values come from environment variables or a secrets file — never stored in the connector file itself.

---

## Connector Lifecycle

```
Write .connector.json
  └─ validate with elliot-core (Pydantic)
     └─ load into ConnectorCache (TTL 30s + mtime watch)
        └─ tool call arrives
           └─ ToolExecutor fetches live data → ingests into SQLite → runs SQL
              └─ AuditLog records result
                 └─ rows returned to caller
```

---

## MCP Tool Categories

| Category | Meaning | Examples |
|---|---|---|
| `READ` | Returns data, no side effects | `list_orders`, `get_customer` |
| `WRITE` | Modifies state | `create_ticket`, `update_status` |
| `ACTION` | Triggers a process | `send_email`, `kick_off_export` |

---

## In-Memory SQLite Pattern

For every tool call:
1. A fresh `SQLiteEngine` is created (no persistent state between calls)
2. Live data is fetched from each required source
3. Nested JSON is flattened into tabular rows
4. Rows are ingested as a SQLite table named after the source `id`
5. The tool's SQL query runs against the in-memory tables
6. Results are returned and the engine is discarded

This means:
- No stale cache between calls
- SQL joins across multiple sources work out of the box
- No database to manage or migrate
