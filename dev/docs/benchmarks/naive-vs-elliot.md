# Benchmark: naive MCP wrapper vs Elliot connector

> The proof-by-contrast asset from `../AGENT_EXPERIENCE_STRATEGY.md` §3.
> Status: **protocol drafted — not yet run.** Nothing from this file may be
> quoted in marketing until the run exists, is reproducible, and includes
> the losses.

## Question

For the same API and the same tasks, how much better does an agent perform
with an Elliot connector than with a naively auto-generated MCP wrapper?
"Better" is measured, not asserted: success rate, tokens per successful
task, unrecovered errors, wrong-tool selections.

## Subjects

| | Arm A — naive | Arm B — Elliot |
|---|---|---|
| Source | Swagger Petstore OpenAPI spec | same spec |
| MCP server | generic OpenAPI→MCP auto-generation (e.g. FastMCP `from_openapi`), zero curation: spec descriptions as tool descriptions, raw JSON responses passed through | the `openapi-petstore` template shipped in `elliot-core/templates/`, linted to zero errors, with its skills |
| Rule | **no strawman** — Arm A is what a reasonable engineer gets in five minutes, configured per its own docs | **no cheating** — Arm B gets no task-specific hints; only what any Elliot user gets from `elliot lint` + the builder |

Petstore first because it is public, stable, and neutral. A second subject
(a real-world API, e.g. GitHub) follows once the protocol survives round 1 —
that answer preempts "toy example."

## Task list (v1 — 10 tasks, one per failure mode we claim to fix)

| # | Task (natural language, given to the agent verbatim) | Probes |
|---|---|---|
| 1 | "Find the pet named 'doggie' and tell me its status." | basic lookup |
| 2 | "List all pets that are currently available." | filtered search |
| 3 | "How many pets are sold vs available?" | aggregation over results |
| 4 | "Get the details of order 3, then tell me about the pet it refers to." | multi-step chaining |
| 5 | "What's the status of pet id 999999999?" | error recovery — must report *not found*, not crash or hallucinate |
| 6 | "Add a new pet called 'benchy', category dogs, status available, then confirm it exists." | write + verify |
| 7 | "Update benchy's status to sold." | tool selection among similar write tools |
| 8 | "Show me everything about the store's inventory." | result sizing — naive arm gets the raw dump |
| 9 | "Is the user 'user1' registered? What's their email?" | ambiguous phrasing → tool choice |
| 10 | "Delete the pet you created earlier and confirm it's gone." | state carry-over + error-shape on the final (expected) 404 |

## Protocol

- **Harness:** the same agent for both arms — Claude Code headless
  (`claude -p`), pinned to one model ID, default settings, connected to
  exactly one MCP server per run.
- **Runs:** each task × each arm × **5 repetitions** (fresh session each
  time; no shared context). Task order randomized per repetition.
- **Judging:** success is judged from the final answer against a written
  rubric per task (in the runner script), by an LLM judge with the rubric —
  spot-checked by a human on 20% of transcripts. Judge never sees which arm.
- **Collected per run:** success (bool), total input+output tokens, number
  of tool calls, wrong-tool selections (tool called ≠ any tool on the
  task's valid path), unrecovered errors (error result not followed by a
  successful retry or a correct "cannot do" answer), wall-clock seconds.
- **Reported:** per arm — success rate, median tokens per *successful*
  task, mean tool calls, unrecovered-error count; plus the per-task
  breakdown table and all transcripts.

## Honesty rules

1. Publish every number, including tasks where the naive arm ties or wins.
2. The runner script, both server configs, and all transcripts are committed
   under `scripts/benchmarks/naive_vs_elliot/` — one command re-runs it all.
3. Petstore's public server is flaky; runs use a locally hosted Petstore
   container so both arms hit identical backend behavior.
4. Model version, date, and harness version are printed in the results
   header. Results are re-run when the pinned model is deprecated.

## Deliverables

- [ ] `scripts/benchmarks/naive_vs_elliot/run.py` — orchestrates both arms.
- [ ] Locally hosted Petstore (docker-compose service) + Arm A server config.
- [ ] Judge rubrics (one per task) in the runner.
- [ ] `dev/docs/benchmarks/results/` — raw transcripts + generated table.
- [ ] This file updated with the headline table — which then leads the
      README, the website, the Cloud landing, and the launch post.
