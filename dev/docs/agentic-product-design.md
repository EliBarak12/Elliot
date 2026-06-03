# Elliot — Agentic Product Design

## The Real Problem

Most products were built for humans. Humans navigate UIs, read documentation, and recover from ambiguous errors by trying something else. **AI agents are not humans.** They make decisions based on tool descriptions, they can’t retry without guidance, they have limited context windows, and they fail silently when tools are poorly designed.

The question Elliot answers is not *“can Claude call my API?”* It is:

> **“Is my product genuinely agent-ready — and how do I know?”**

---

## What a Connector Is

A **Connector** represents a **business domain** — not a single API or database.

One connector can span any number of underlying data sources: REST APIs, PostgreSQL tables, MySQL tables, CSV files, JSON files. All data is ingested into an in-memory SQLite database so tools can JOIN across sources in a single query.

```
Connector: "Customer 360"
├── Source: crm_api         REST  → https://api.crm.com/contacts
├── Source: orders_db       Postgres → orders table
├── Source: segments_file   CSV → ./data/segments.csv

  Tool: get_customer_overview
    source_ids: [crm_api, orders_db, segments_file]
    sql: >
      SELECT c.name, c.email, COUNT(o.id) AS total_orders,
             s.segment_name
      FROM crm_api c
      LEFT JOIN orders_db o ON c.id = o.customer_id
      LEFT JOIN segments_file s ON c.segment_id = s.id
      WHERE c.id = :customer_id

  Tool: list_recent_orders
    source_ids: [orders_db]
    sql: >
      SELECT id, total, status, created_at
      FROM orders_db
      WHERE customer_id = :customer_id
      ORDER BY created_at DESC
      LIMIT :limit
```

An agent using this connector can ask “what’s the full picture for customer X?” and get a single, compact, JOIN’ed result — not three separate tool calls.

### Source types

| Type | What it connects to | Table name in SQLite |
|---|---|---|
| `rest` | Any REST API (GET or POST) | `source.id` |
| `postgres` | PostgreSQL table or query | `source.id` |
| `mysql` | MySQL table or query | `source.id` |
| `file` | CSV, JSON, or JSONL file on disk | `source.id` |

### How cross-source tools work

1. Agent calls tool `get_customer_overview` with `{customer_id: 42}`
2. Elliot fetches `crm_api`, `orders_db`, and `segments_file` **in parallel**
3. All three are ingested into the same in-memory SQLite as tables named after their `id`
4. The tool’s SQL runs as a JOIN across all three tables
5. Compact, shaped result is returned to the agent
6. SQLite is discarded — nothing persists

---

## What “Agentic Native” Means

A product is **agentic native** when:

1. **Agents discover the right tool automatically** — because tool descriptions are precise, verb-first, and unambiguous
2. **Agents call tools correctly on the first try** — because parameters are named clearly and types are explicit
3. **Agents recover cleanly from errors** — because errors are structured, actionable, and tell the agent what to do next
4. **Results fit in the agent’s context window** — because tools return the minimum data needed, not full table dumps
5. **No token waste** — because result shapes are compact and consistent

If any of these five conditions fails, agents either hallucinate, retry in circles, or give up.

---

## The Feedback Loop Elliot Provides

```
  ┌──────────────────────────────────────────┐
  │     Design your connector (domain-first)    │
  │  Agent helps via agentic builder tools      │
  └─────────────────┼───────────────────────┘
                   ↓
  ┌──────────────────────────────────────────┐
  │      Lint — static quality check            │
  │  elliot lint my-domain.connector.json       │
  └─────────────────┼───────────────────────┘
                   ↓
  ┌──────────────────────────────────────────┐
  │      Eval — validate against live data      │
  │  elliot eval my-domain.eval.yaml            │
  └─────────────────┼───────────────────────┘
                   ↓
  ┌──────────────────────────────────────────┐
  │      Deploy to real agents                  │
  │  Claude Code / Codex / any MCP client       │
  └─────────────────┼───────────────────────┘
                   ↓
  ┌──────────────────────────────────────────┐
  │      Observe real agent sessions            │
  │  Studio Agent Console → full trace          │
  └─────────────────┼───────────────────────┘
                   ↓
  ┌──────────────────────────────────────────┐
  │      Improve based on data                  │
  │  token cost, error rate, retry rate         │
  └──────────────────────────────────────────┘
                   ↓ (back to Design)
```

---

## The Five Principles of Agent-Ready Tools

### 1. Descriptions are contracts, not labels

| Bad | Good |
|---|---|
| `"Get data"` | `"Return all animals, optionally filtered by species and status"` |
| `"User info"` | `"Get a single user by their integer ID. Returns 404 error if not found."` |
| `"Run query"` | `"Count orders placed in the last N days, grouped by status"` |

**Rule**: Start with a verb. State what the tool returns. State key parameters. State what errors are possible.

### 2. Parameters are typed and named for agents, not humans

| Bad | Good |
|---|---|
| `q: string` | `search_query: string — "keyword to match against animal name"` |
| `n: integer` | `limit: integer — "max rows to return, default 20"` |
| `f: boolean` | `include_archived: boolean — "if true, include soft-deleted records"` |

### 3. Results are sized for context windows

Every tool should return the minimum data needed. The `response_shape.fields` list controls which columns come back. Aim for < 500 tokens per result. Flag > 2000 as high risk.

### 4. Errors tell agents what to do next

```json
{ "error": { "code": "VALIDATION_INVALID_SPECIES",
             "message": "species must be one of: dog, cat, bird, fish",
             "details": { "valid_values": ["dog", "cat", "bird", "fish"] } } }
```

### 5. Tool sets are minimal and orthogonal

Start with 3–5 tools. Cross-source JOINs let you merge what used to be separate tools into one — fewer decisions for the agent, less token cost on tool discovery.
