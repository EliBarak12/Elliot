---
name: compose-skill
description: Compose a multi-step Elliot skill — a named sequence of connector tool calls that the runtime exposes as one MCP tool. Use when a single user-level job-to-be-done needs more than one tool to answer, and you want the agent to invoke it as a single call instead of orchestrating the chain itself.
when_to_use: Trigger when the user says "combine these tools", "make one tool that does X and Y", "compose a workflow", "agents shouldn't have to chain these", or when audit transcripts show the agent always calling the same N tools in sequence to answer one question.
argument-hint: "[skill name]"
allowed-tools: Bash mcp__elliot__*
---

# Compose Skill Workflow

You are turning a recurring multi-tool chain into one named **session skill**.
A skill is a step list — each step is a tool call whose result the next step
can reference — that the runtime exposes as a single MCP tool to downstream
agents. Done well, it collapses three or four agent turns into one.

> Vocabulary note. "Skill" here is the *runtime concept* (a chained tool
> sequence stored in the session, defined via `elliot_create_skill`). It is
> NOT a SKILL.md file like the one you are reading — those are workflow
> guides for *you*, the agent. Don't conflate them.

## When a skill is worth composing

Compose a skill when **all** of these are true:

1. The job-to-be-done always needs ≥ 2 tool calls, in the same order.
2. The first tool's output feeds the second's parameters (e.g. "look up the
   customer id, then summarise their orders").
3. The downstream agent's prompt does not need to see the intermediate
   results — only the final answer.

If the agent often branches between two different second-step tools based on
the first tool's output, that's a *workflow*, not a deterministic chain — but
it can still be a connector skill. Author it as a **prose skill**: call
`elliot_create_skill` with `instructions` (markdown describing the workflow,
branches and all) and `when_to_use`, and leave `steps` empty. On export it
becomes a `SKILL.md` guide alongside the connector's tools — exactly like the
hand-written guides Elliot ships for itself. A skill may carry both `steps`
(the happy-path chain) and `instructions` (the surrounding judgement).

## Steps

### 1. Confirm the chain

Call `elliot_list_tools` to see what's registered. Identify the exact tool
ids the chain uses and read each with `elliot_get_tool(tool_id)` to confirm
its parameters and what it returns.

### 2. Sketch the steps

For each step, decide:
- `alias` — short name you'll reference the result by (e.g. `customer`,
  `orders`).
- `tool_id` — the registered tool's id.
- `params` — the literal parameter dict. To thread a previous step's row
  into this one, use the alias: `{"customer_id": "{{ customer.rows[0].id }}"}`.

### 3. Define `input_parameters`

These are the parameters the skill *itself* takes — the inputs the downstream
agent will pass. They're separate from per-step params: they're substituted
in wherever you reference them (`{{ inputs.<name> }}`).

Keep them tight — one or two named parameters. A skill with seven inputs is
usually two skills.

### 4. Create the skill

Call `elliot_create_skill(name, description, steps, input_parameters)`. The
description follows the same contract as a tool description: verb-first,
unambiguous, says what it returns and when to use it.

The keys `arguments`, `args`, `parameters`, and `inputs` are accepted as
aliases for `params` in a step; `tool` is accepted as `tool_id`. Use the
canonical names anyway — agents copying your skill back later won't have to
guess.

### 5. Preview it

Call `elliot_preview_skill(skill_id, inputs={...})` with the input
parameters. It executes every step against the session's SQLite sandbox and
returns the final result. If any step fails, fix the offending step's
`params` template or the underlying tool, then re-create the skill (skills
are immutable — there's no `elliot_update_skill`; delete and re-create with
`elliot_delete_skill`).

### 6. Build, audit, deploy

A skill is part of the connector. Re-run `elliot_build_connector` to roll it
into the built config — `tool_count` and `skill_count` should both reflect
the new total. Re-run `elliot_lint_connector` and the audit (`audit-connector`
skill) so sub-agents exercise the new skill end-to-end. Then `deploy`.

## Inspecting skills

- `elliot_list_skills` — every skill in the session with step counts.
- `elliot_get_skill(skill_id)` — the full definition (steps, input
  parameters).
- `elliot_delete_skill(skill_id)` — remove it (compose-fresh is the only
  way to "edit" a skill).

## Rules

- Skills do not loop or branch. If you need conditional logic, write a real
  tool that runs the SQL/HTTP itself; do not try to express it as a skill.
- Skills run against the same sandbox as `elliot_preview_tool`. Anything an
  individual tool can't reach, a skill can't reach either.
- Don't compose a skill that wraps a single tool. That's a rename, not a
  skill — use `elliot_update_tool` to rename it.
