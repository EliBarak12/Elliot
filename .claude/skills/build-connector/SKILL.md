---
name: build-connector
description: Build an Elliot connector from an API or database. Use when the user wants to connect a new data source, create MCP tools, or wrap an API for agents.
argument-hint: "[connector-name]"
when_to_use: Trigger when user says "create a connector", "connect my API", "wrap my database", "make my API agent-ready", or similar.
allowed-tools: Bash mcp__elliot__*
---

# Build Connector Workflow

You are helping build an Elliot connector — a JSON definition that turns a data source into agent-ready MCP tools.

## Current workspace state
Connectors directory: !`ls connectors/ 2>/dev/null || echo "(empty)"`
MCP plugin status: !`curl -s http://localhost:3000/health 2>/dev/null || echo "not running — start with: honcho start"`

## Steps

### 1. Set connector context
Call `elliot_set_context` with the connector name and a description of the product.

### 2. Discover the source
Call `elliot_discover_source` with the API base URL or database connection string.
Ask the user for:
- Auth type (bearer token, API key, basic, none)
- Any env var names holding credentials (never the values)

### 3. Explore data shape
Use `elliot_query_sql` to run sample queries once the source is loaded.
Understand what data is available before designing tools.

### 4. Design tools
For each tool, call `elliot_create_tool`. Follow these rules:
- Description must start with a verb ("List", "Search", "Get", "Create")
- Description must say what it returns and when to use it
- Use READ category for queries, WRITE for mutations, ACTION for operations
- Set `limit` to 20-100 for list tools — never dump all rows
- Add parameters with clear names and descriptions

### 5. Validate and lint
Call `elliot_lint_connector` — fix every issue before saving.
Call `elliot_validate_connector` to check schema correctness.

### 6. Save
Call `elliot_save_connector` to write `connectors/<slug>.connector.json`.

### 7. Test
Use the Playground in Studio (http://localhost:5173) or call `elliot_run_eval` if an eval suite exists.

## Quality checklist
- [ ] Every tool description starts with a verb
- [ ] Every tool has a LIMIT to cap response size
- [ ] No raw API keys or secrets in the connector file
- [ ] READ tools have no side effects
- [ ] Lint passes with zero issues
