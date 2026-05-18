---
name: build-connector
description: Build an Elliot connector that turns an API or database into agent-ready MCP tools. Use when the user wants to connect a new data source, wrap an existing API, or make their database queryable by AI agents.
argument-hint: "[connector-name or API URL]"
when_to_use: Trigger when user says "connect my API", "create a connector", "wrap my database", "make my API agent-ready", "turn my REST API into tools", or similar.
allowed-tools: Bash mcp__elliot__*
---

# Build Connector Workflow

You are building an Elliot connector — a JSON definition that wraps a data source in agent-ready MCP tools.

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
Use `elliot_query_sql` to run sample queries and understand what columns exist.
Do this before designing tools — never guess field names.

### 4. Design tools (one per agent operation)
For each tool call `elliot_create_tool`:
- `description` MUST start with a verb: "List", "Search", "Get", "Create", "Update", "Delete"
- Include: what it returns, when to use it, key constraints
- Set `limit` to 20–50 for list tools — never return all rows unfiltered
- Use `category`: READ for queries, WRITE for inserts/updates, ACTION for operations
- Add typed `parameters` with clear names (prefer `user_id` over `user`, `start_date` over `from`)
- For constrained strings, add `enum` values

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

Example good SQL:
```sql
SELECT id, name, email, plan
FROM "users"
WHERE (:plan IS NULL OR plan = :plan)
  AND status = 'active'
ORDER BY mrr DESC
LIMIT 20
```

### 5. Validate
Call `elliot_lint_connector` — fix every issue it reports before saving.
Call `elliot_validate_connector` to confirm schema is valid.

### 6. Save
Call `elliot_save_connector` — writes `connectors/<slug>.connector.json`.

### 7. Test in the playground
Open Studio at http://localhost:5173 and exercise each tool.
Or call `elliot_run_eval` if an eval suite exists.

## Rules
- Never put API key values in the connector file — only env var names with `{{ env:VAR_NAME }}`
- Every READ tool needs a LIMIT
- Lint must pass before saving
