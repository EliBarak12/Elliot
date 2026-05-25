---
name: build-connector
description: Build an Elliot connector that turns an API or database into agent-ready MCP tools. Use when the user wants to connect a new data source, wrap an existing API, or make their database queryable by AI agents.
argument-hint: "[connector-name or API URL]"
when_to_use: Trigger when user says "connect my API", "create a connector", "wrap my database", "make my API agent-ready", "turn my REST API into tools", or similar.
allowed-tools: Bash mcp__elliot__*
---

# Build Connector Workflow

You are building an Elliot connector — a JSON definition that wraps a data source in agent-ready MCP tools.

## The tool sequence

Build always follows this order — each tool depends on the one before it:

```
elliot_set_context      → name the connector + product
elliot_discover_source  → register the API / DB, materialize its tables
elliot_query_sql        → inspect the real columns before designing tools
elliot_create_tool      → define one tool (verb-first description + SQL)
elliot_preview_tool     → run that tool against sandbox data, verify rows
elliot_build_connector  → assemble all registered tools into a connector
elliot_lint_connector   → check the built connector; fix, rebuild, re-lint
elliot_export_connector → write the connector file to disk
```

`elliot_lint_connector`, `elliot_run_eval`, and `elliot_export_connector` all
operate on the connector produced by `elliot_build_connector` — if you skip the
build step they have nothing to work on.

## Workspace state
Existing connectors: !`ls connectors/*.connector.json 2>/dev/null | xargs -I{} basename {} .connector.json | tr '\n' ', ' || echo "(none yet)"`
Elliot plugin: !`curl -s http://localhost:3000/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "not running — start Elliot first: honcho start"`

## Steps

### 1. Name the connector
Call `elliot_set_context` with:
- `connector_name`: slug-style name (e.g. "acme-crm")
- `description`: one sentence describing the product

### 2. Describe the source
Call `elliot_discover_source`. Collect from the user:
- Base URL (for REST) or connection string format (for DB — never log the value)
- Auth type: `bearer`, `api_key`, `basic`, or `none`
- Env var name holding the credential (e.g. `ACME_API_KEY`)
- Pagination style if REST: `cursor`, `offset`, `page`, `link_header`, or `none`

### 3. Explore the data shape
First, see what's loaded — call `elliot_list_sources` for a roster of every
discovered source (table name, row count, columns).

Then explore the data:
- `elliot_query_sql` — run ad-hoc SELECTs to understand what columns exist.
- `elliot_sample_data(table_name, limit=10)` — random rows (useful for edge
  cases, not just the first N).
- `elliot_profile_source(table_name)` — column statistics: min, max, nulls,
  distinct count, top 5 values. Use this when you're about to add an enum
  parameter and need to know the real set of values.
- `elliot_profile_column(table_name, column_name)` — same stats for one
  column only, when you only care about that one.

Do this before designing tools — never guess field names. If you loaded the
wrong source, drop it with `elliot_remove_source(source_id)` and re-discover.
If the upstream changed and you want fresh data, call
`elliot_refresh_source(source_id)`.

### 4. Design tools (one per agent operation)

**Design domain tools, not endpoint wrappers.** A tool should answer a real
question the user's product cares about — "revenue by month", "customers at
churn risk", "open tickets for this account" — not just mirror one API route
or one table. Name and shape each tool around the *job*, not the data layout.

**Cover the whole source.** Walk every table, endpoint, and file that
`elliot_discover_source` surfaced and make sure the tool set reaches every
entity and operation an agent would realistically need across the user's API,
database, or files. A connector that exposes only the first table is
incomplete — map the full domain.

**Make tools calculate and aggregate — don't dump rows.** When the agent's
real question is "how many", "what's the total", "what's the average", "which
are the top N", or "break this down by X", answer it *inside the tool* with
SQL `COUNT`, `SUM`, `AVG`, `MIN`/`MAX`, `GROUP BY`, and `ORDER BY ... LIMIT`.
Return the computed answer, not the raw table. An aggregation tool is both
more useful to the agent and far cheaper in tokens than a row dump it would
have to count itself. Pair a few raw "list/get" tools with several
aggregation/metric tools so the agent rarely has to post-process data.

For each tool call `elliot_create_tool`:
- `description` MUST start with a verb: "List", "Search", "Get", "Count", "Summarize", "Create", "Update", "Delete"
- Include: what it returns, when to use it, key constraints
- Set `limit` to 20–50 for list tools — never return all rows unfiltered
- Use `category`: READ for queries (including aggregations), WRITE for inserts/updates, ACTION for operations
- Add typed `parameters` with clear names (prefer `user_id` over `user`, `start_date` over `from`)
- For constrained strings, add `enum` values
- Prefer returning a small computed result (counts, totals, grouped rows) over a large raw set

**SQL conventions** — the runtime executes against in-memory SQLite:
- Reference parameters with a **colon prefix**: `WHERE plan = :plan` — declare
  each one in the tool's `parameters` list. **NOT** `{{ plan }}` (Jinja) or
  `$plan` (Bash); SQLite parses neither and the runtime will reject the SQL
  at `elliot_create_tool` time.
- Refer to source tables by the **logical name** you passed to
  `elliot_discover_source` (and quote with double quotes if it contains
  punctuation): `FROM "users"`, `FROM "purchase_orders"`.
- **Flattener linkage columns**: every materialized table — primary or
  child — carries an auto-injected `_id` (sequential within the table)
  and every child table also carries a `_parent_id` pointing at its
  parent's `_id`. JOIN through them when the upstream JSON has no
  natural foreign key:
  ```sql
  -- e.g. insights[].teaserblocks[]: one teaserblock_count per insight
  SELECT i.title, COUNT(t._id) AS teaserblock_count
  FROM "insights" i
  LEFT JOIN "insights_teaserblocks" t ON t._parent_id = i._id
  GROUP BY i._id
  ```
  Child tables also carry `_index` (zero-based position within the
  parent's array) — handy for "first item" lookups.
- Flattener-produced child tables are named `{source}_{field}` — e.g. an
  `orders` source whose rows contain a `line_items[]` array gives you a
  child table `orders_line_items` you can JOIN through `_parent_id`.

Example good description:
> "Search customers by name or email. Use before create_customer to avoid duplicates. Returns id, name, email, plan. Max 20 results."

Example good SQL — a raw list tool:
```sql
SELECT id, name, email, plan
FROM "users"
WHERE (:plan IS NULL OR plan = :plan)
  AND status = 'active'
ORDER BY mrr DESC
LIMIT 20
```

Example good SQL — an aggregation tool (`Summarize revenue by plan`). It
returns one short row per plan instead of every user, so the agent gets the
answer directly:
```sql
SELECT plan,
       COUNT(*)        AS customers,
       SUM(mrr)        AS total_mrr,
       ROUND(AVG(mrr)) AS avg_mrr
FROM "users"
WHERE status = 'active'
GROUP BY plan
ORDER BY total_mrr DESC
```

Before saving a tool, dry-run its SQL with `elliot_validate_sql(sql)` —
it catches syntax errors, multi-statement attacks, and forbidden operations
(DDL, ATTACH, PRAGMA) without executing. If a tool runs slow once preview-loaded,
call `elliot_explain_query(sql)` to see SQLite's query plan. To validate a full
tool definition without committing it to the registry, call
`elliot_validate_tool(tool_dict)` — same shape as `elliot_create_tool` but no save.

After creating each tool, call `elliot_preview_tool` with its id to run its
SQL against the sandbox data and confirm it returns sensible rows. Fix the SQL
before moving on — never leave an unverified tool in the registry.

### 5. Build the connector
Call `elliot_build_connector` with `name`, `slug`, and `description`. This
assembles every tool you registered into one connector config, held in the
session. Re-run it whenever you add, change, or remove a tool — lint, eval,
and export all work off the *built* connector, not the loose tool registry.

### 6. Lint
Call `elliot_lint_connector` — it lints the connector you just built and takes
no arguments. Fix every error and warning, call `elliot_build_connector` again
to rebuild, then re-lint. Repeat until it reports zero issues.

### 7. Export
Call `elliot_export_connector` to write the connector to disk. Pass `path`
(e.g. `connectors/<slug>.connector.json`); it defaults to
`.elliot/connector.json`.

### 8. Test
Run `elliot_run_eval` if an eval suite exists, or open Studio at
http://localhost:5173 to exercise each tool.

## What a good connector looks like

Hold the build to this bar — it is what `elliot_lint_connector` and
`elliot_quality_scan` measure, and what the audit sub-agents will exercise:

- **Domain tools, not endpoint or table wrappers.** Each tool answers a real
  question the product cares about or performs a real operation. "Summarize
  revenue by plan" beats "dump the users table". If two endpoints serve one
  job, expose one tool.
- **The set covers the whole source.** The tools span every entity and
  operation an agent would realistically need across the user's API, database,
  or files — not just the first table the discovery surfaced.
- **Calculation and aggregation live in the tools.** Counts, totals, averages,
  top-N, and grouped breakdowns are computed in SQL and returned ready to use,
  so the agent gets answers instead of raw data to post-process.
- **Every description is a contract.** It starts with a verb, says what the
  tool returns, when to use it, and its key limit — written for an agent that
  has never seen the API.
- **Results are sized for a context window.** Every READ tool has a LIMIT and
  an explicit column list (never `SELECT *`); aggregation tools return a
  handful of computed rows. A typical call should return well under ~1000
  tokens.
- **Parameters are typed and specific.** `user_id` not `user`, `start_date`
  not `from`; `enum` values for constrained strings; required vs. optional set
  deliberately.
- **Errors are actionable.** A failing call tells the agent what to do next —
  never a bare stack trace.
- **Annotations are deliberate.** `readOnlyHint` / `destructiveHint` /
  `openWorldHint` reflect what the tool really does — downstream agents use
  them to decide whether to confirm before calling.
- **Clean lint, strong score.** Zero lint errors *and* zero warnings;
  `elliot_quality_scan` ≥ 80 before you export.

## Rules
- Never put API key values in the connector file — only env var names with `{{ env:VAR_NAME }}`
- Every READ tool needs a LIMIT
- `elliot_build_connector` must be called before lint, eval, or export
- Lint must pass before exporting
