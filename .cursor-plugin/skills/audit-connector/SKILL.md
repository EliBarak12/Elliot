---
name: audit-connector
description: Run a Petri-style parallel audit of an Elliot connector — spawn 5 sub-agents that try to use the connector for real, capture every failure, score the run on graded dimensions, and drive a fix loop until the connector passes. Use after a connector is built and linted, before deploying it.
when_to_use: Trigger when the user says "audit my connector", "test the connector with agents", "make sure agents can use this", "run the audit", "is my connector good enough", or after build-connector / lint-connector when the connector is ready to validate.
argument-hint: "[connector name]"
allowed-tools: Bash Task mcp__elliot__*
---

# Audit Connector Workflow

You are auditing a built connector the way Anthropic's Petri audits a model:
real agent tasks, parallel auditors, transcripts as the signal, and a judge
that scores graded dimensions with cited evidence. The connector must already
be built (`elliot_build_connector`) — the audit runs against it.

## Steps

### 1. Generate audit seeds
Call `elliot_generate_audit_seeds` (count defaults to 5). It returns seeds
(realistic agent tasks derived from the product intent and the tools), the
scoring rubric, and the spawn instructions.

### 2. Spawn 5 parallel sub-agents
Spawn one sub-agent per seed **in parallel** (a single message with multiple
Task calls). Brief each sub-agent like this:

> You are an AI agent whose ONLY tools are this connector's tools. Accomplish
> this task: `<seed.task>`. Exercise each tool by calling `elliot_preview_tool`
> with the tool id and arguments — this runs the tool against the sandbox
> data. Pick argument values from the parameter descriptions; do not guess
> blindly. Follow the rubric. Return a transcript: for every call record
> `tool_id`, `arguments`, `ok`, `error_code`, `error_message`,
> `result_row_count`, `result_token_estimate`, and a short `note` when
> something was confusing. Also return `task_completed` (bool) and a one-line
> `summary`.

The sub-agents run against the in-memory sandbox — the audit is safe and makes
no real API calls.

### 3. Submit transcripts
For each sub-agent, call `elliot_submit_audit_transcript` with its transcript
JSON (`seed_id`, `task`, `agent_label`, `calls`, `task_completed`, `summary`).

### 4. Judge
Call `elliot_judge_audit`. It scores seven dimensions 1-10 (task_completion,
tool_reliability, error_actionability, token_efficiency, schema_clarity,
tool_selection, scenario_coverage) and returns findings that each cite the
exact failing call.

### 5. Fix loop
For every **error**-severity finding (and ideally the warnings too):
- Edit the offending tool — tighten the description, fix a parameter name or
  type, add an enum, add a LIMIT, or make an error message actionable.
- Rebuild with `elliot_build_connector` and re-lint.
- Call `elliot_clear_audit_transcripts`, then re-run from step 1.

Repeat until `elliot_judge_audit` returns `passed: true`. Cap at 4 iterations —
if it still fails, report the remaining findings to the user and ask how to
proceed.

### 6. Report
Summarize the final report for the user: pass/fail, dimension scores, and what
was fixed across the iterations.

## Rules
- Always spawn the sub-agents in parallel — one message, multiple Task calls.
- Clear transcripts between iterations so each judge run is clean.
- Never mark the connector ready while error-severity findings remain.
