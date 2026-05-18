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

### 1. Lint
Call `elliot_lint_connector`. **Do not proceed if any errors are reported.**
Fix all issues, re-lint, confirm zero errors.

### 2. Validate
Call `elliot_validate_connector`. Confirms schema integrity.

### 3. Eval
If an eval suite exists: call `elliot_run_eval`.
All cases must pass. Fix failures before deploying.

### 4. Save
Call `elliot_save_connector` to write the final connector file.

### 5. Activate on the runtime
The connector-runtime auto-loads `*.connector.json` files from the `connectors/` directory with a 30-second TTL cache. After saving:

```bash
# Force cache refresh
curl -X POST http://localhost:3001/v1/observations/prune
```

Verify the tools are live:
```bash
curl -s http://localhost:3001/v1/health | python3 -m json.tool
```

### 6. Test via MCP
The tools are now available as MCP tools at `http://localhost:3001/mcp`.
Add to Claude Code: the `.mcp.json` in this project already points there.

## Checklist
- [ ] Zero lint errors
- [ ] Zero lint warnings
- [ ] All eval cases pass
- [ ] Health endpoint shows connector loaded with correct tool count
- [ ] At least one manual test call succeeded in the playground
