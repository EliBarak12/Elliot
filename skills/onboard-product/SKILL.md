---
name: onboard-product
description: Guided onboarding for turning a product into an agentic product with Elliot. Use this as the FIRST step when a user wants to make their API or database agent-ready — it interviews the user about their product and how agents should use it before any tool is designed, so the connector reflects intent instead of guesswork.
when_to_use: Trigger when the user says "make my product agentic", "I want agents to use my product", "onboard my API", "turn my product into agent tools", "help me get started building a connector", or when they have an API/Postman collection and aren't sure what tools to expose.
argument-hint: "[product name or API collection URL]"
allowed-tools: Bash mcp__elliot__*
---

# Onboard Product Workflow

You are onboarding a user's product into Elliot. Do **not** look at their data
and decide the tools yourself. The whole point of this workflow is that the
tools reflect what the *user* wants agents to do. Interview first, design second.

## Workspace state
Elliot plugin: !`curl -s http://localhost:3000/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "not running — start Elliot first: make dev"`

## Steps

### 1. Import the user's API collection
Ask the user for whatever description of their API they already have:
- An **OpenAPI 3.x** spec (URL or JSON), or
- A **Postman Collection** export (JSON), or
- Raw docs / `curl` examples — if so, help them turn it into one of the above.

Call `elliot_import_api_collection` with the spec/collection. It returns a set
of *proposed* tools with token-risk hints. Do not build from this yet — it is
input to the interview, not the answer.

### 2. Interview the user
Ask these questions, one topic at a time, in plain language. Wait for answers.
- **Who are the agents?** What product will call these tools (support bot,
  internal copilot, a customer-facing assistant)?
- **What jobs should agents do?** Get 3-6 concrete tasks, phrased as a user
  goal ("find a customer's open invoices and email a reminder"). These matter
  most — they become the audit seeds later.
- **What should be exposed vs hidden?** Which operations agents should have,
  and which to keep off-limits.
- **What is destructive?** Which operations mutate data or are irreversible
  and should require a confirmation gate.
- **What is sensitive?** Field names that must never reach an agent (PII,
  secrets, internal flags).
- **Scale?** Roughly how much data a typical result spans.

Record the answers with `elliot_record_product_intent`.

### 3. Propose the tool set
Map each job-to-be-done to one **domain tool** — named for the job, not the
API route. Where a job is a question ("how many", "what's the total", "top
accounts", "breakdown by month"), propose an aggregation tool that computes
the answer in SQL rather than a tool that dumps raw rows. Make sure the set
spans the whole source — every entity and operation agents need across the
user's API, DB, or files. Cross-check against the imported collection and the
intent. Present the proposed tool list to the user with a one-line rationale
per tool, and **confirm with them** before building. Drop anything agents
don't need — fewer, sharper tools beat many.

### 4. Build the connector
Follow the `build-connector` prompt to discover the source, explore the data
shape, and create each tool. Honor the five principles — descriptions are
verb-first contracts, results are sized, errors are actionable.

### 5. Scan
Call `elliot_build_connector` to assemble the connector, then `elliot_lint_connector`
and fix every issue. The linter also flags generic parameter names, enum
candidates, missing pagination, and any tool that returns a field the user
marked sensitive. For a deeper quality report, call `elliot_quality_scan`.

### 6. Audit with parallel sub-agents
Invoke the `audit-connector` prompt. It runs 5 parallel sub-agents that try to
use the connector for real, captures their failures, and drives a fix loop.

### 7. Export and deploy
Once the audit passes, call `elliot_build_connector` then `elliot_export_connector`
to write the connector file, then follow the `deploy` prompt.

## Rules
- Interview before you design. Never skip step 2.
- One tool per job-to-be-done — resist exposing every endpoint.
- Never record secret values in the product intent — only field *names*.
- Do not move past step 6 until the audit report `passed` is true.
