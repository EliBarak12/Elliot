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

### 4. Ship it

**On Elliot Cloud (the marketplace default) — one call:** `elliot_cloud_publish`.
It runs a publish-time smoke gate first (a cache-safe runtime build + `tools/list`
+ a per-tool execute of each auto-callable READ tool), so a connector that would
404 on every agent call is blocked instead of shipped. On success it deploys to a
stable public MCP URL on your tenant and returns it. If it blocks (`lint_errors`,
`missing_secrets`, `smoke_failed`), fix and re-publish. Choose who can call it
with `auth_mode`: `api_key` (default, shared key), `personal` (your workspace
only), `third_party_oauth` (each user connects their own upstream account), or
`open` (anyone, no key — non-sensitive data only). **This is the whole deploy on
Cloud — skip the local steps below.**

**Running Elliot locally instead:**
- `elliot_export_connector` — write the connector file (`path`, or the
  `.elliot/connector.json` default).
- `elliot_start_runtime` — launch the connector-runtime subprocess. Pass
  `connector_path` if you exported to a non-default path, or it loads the wrong
  (or no) connector. Confirm with `elliot_runtime_logs`; get the agent URL with
  `elliot_get_connection_config`; stop later with `elliot_stop_runtime`.
  (These tools are local-only — they aren't served on Elliot Cloud.)

### 5. Connect agents
The tools are now served over MCP. On Cloud, give agents the public URL from
`elliot_cloud_publish` (the connector's dashboard page has one-click install
buttons). Locally, use the URL from `elliot_get_connection_config`.

## Checklist
- [ ] Zero lint errors
- [ ] Zero lint warnings
- [ ] Eval cases pass (inline `cases` or a suite)
- [ ] Cloud: `elliot_cloud_publish` returned a public URL (smoke gate passed).
      Local: the health endpoint shows the connector loaded with the right tool count
- [ ] At least one manual test call succeeded in the playground
