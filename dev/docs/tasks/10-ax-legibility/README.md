# Epic 10 — AX Legibility

Product work implied by `dev/docs/AX_STRATEGY.md`: the instruments that make
the value of good agent experience visible in under 60 seconds. The strategy
doc holds the why; these tasks hold the how.

Ordering note: tasks 080–081 are the two gaps verified against the codebase
in the 2026-07 strategy audit. The AX Score, public grader, and README badge
already exist (Cloud's MCP Server Grader + `elliot_core.eval.quality`) and
are deliberately *not* re-specced here.

| Task | Title | Delivers |
|---|---|---|
| [080](080-before-after-benchmark.md) | Before/after AX benchmark harness | `elliot benchmark` — same agent task on a naive spec-generated tool surface vs the Elliot connector, scored side by side |
| [081](complete-081-demo-connector-welcome.md) | Preloaded demo connector + Studio `/welcome` | A new user's first 60 seconds end at a working tool call and a live trace, not an empty dashboard |
| 082 (planned) | "AX Score" naming unification | One name for grader grade / quality scan / eval score across Studio, Cloud, docs |
| 083 (planned) | Eval-in-CI GitHub Action | `elliot lint` + `elliot eval` + AX-score threshold as a reusable workflow |
