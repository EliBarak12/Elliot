---
name: deploy
description: Deploy an Elliot connector to the runtime so agents can use it. Runs the full validation pipeline (lint → eval → deploy) before activating. Use when the user is ready to make their connector live.
argument-hint: "[connector-slug]"
when_to_use: Trigger when user says "deploy", "go live", "activate my connector", "make it available to agents", "ship it", or similar.
allowed-tools: Bash mcp__elliot__*
---

# Deploy Connector Workflow

## Pre-flight status
!`ls connectors/*.connector.json 2>/dev/null || echo "(no connectors)"`
Runtime health: !`curl -s http://localhost:3001/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "not running"`

## Deploy pipeline (must complete in order)

### 1. Build
Call `elliot_build_connector` so the connector reflects the latest tools.
Lint, eval, and export all operate on this built connector.

### 2. Lint
Call `elliot_lint_connector` (no arguments — it lints the built connector).
**Do not proceed if any errors are reported.** Fix all issues, call
`elliot_build_connector` again, re-lint, and confirm zero errors.

### 3. Eval
If an eval suite exists: call `elliot_run_eval`.
All cases must pass. Fix failures before deploying.

### 4. Export
Call `elliot_export_connector` to write the final connector file. Pass `path`
(e.g. `connectors/<slug>.connector.json`) or accept the `.elliot/connector.json`
default.

### 5. Activate on the runtime
Call `elliot_start_runtime`. It launches the connector-runtime subprocess and
loads the connector you just exported (it defaults to the most recently
exported connector). Confirm it came up with `elliot_runtime_logs`, and get
the URL agents should connect to with `elliot_get_connection_config`.

### 6. Connect agents
The tools are now served over MCP by the runtime. Use the URL from
`elliot_get_connection_config` — `elliot connect --runtime` wires it into
every coding agent on the machine, or add it to a client by hand.

## Checklist
- [ ] Zero lint errors
- [ ] Zero lint warnings
- [ ] All eval cases pass
- [ ] Health endpoint shows connector loaded with correct tool count
- [ ] At least one manual test call succeeded in the playground
