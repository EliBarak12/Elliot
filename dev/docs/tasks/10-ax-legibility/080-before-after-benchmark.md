# Task 080 — Before/After AX Benchmark Harness

## Goal

Add `elliot benchmark` — one command that, given an OpenAPI spec and an
Elliot connector built from it, runs the **same seeded agent tasks** against
both tool surfaces and emits a side-by-side scoreboard: tool calls, tokens,
wall time, task success. The output is the "money demo" from AX_STRATEGY
§3.2: the artifact that turns "agent-ready" from an adjective into
arithmetic, reusable as a README GIF, a landing-page hero, and a
content engine ("we benchmarked N public specs…").

## Why

Every MCP generator ships the "before" arm and calls it done. Elliot's
entire pitch is the delta between that and a shaped connector — but today
the delta is invisible. The audit subsystem already produces per-seed
transcripts and a judged verdict; this task packages two arms of it into
one comparable, repeatable, honest number.

**Honesty rules (non-negotiable, they are the product):**
1. The naive arm is derived *mechanically* from the spec — never
   hand-worsened. `analyze_spec()` output, converted 1:1, descriptions
   copied verbatim from the spec's `summary`/`description`, all response
   fields returned, no row caps beyond the runtime's hard safety budget.
2. Both arms: same seeds, same agent model, same live source, same run
   count. Seeds are generated once and reused.
3. Report medians over `--runs N` (default 3), and store every transcript
   so any number in the scoreboard can be traced to a session.
4. The methodology section is part of the output (`report.md`), not a blog
   footnote.

## Implementation

### New package: `packages/core/src/elliot_core/benchmark/`

```
benchmark/
├── __init__.py
├── models.py       BenchmarkArm, BenchmarkRun, BenchmarkReport (Pydantic)
├── naive.py        ProposedConnector → ConnectorConfig, unedited
├── runner.py       drive both arms through the audit machinery
└── report.py       scoreboard: terminal table + report.md + report.json
```

### `models.py`

```python
from __future__ import annotations

from pydantic import BaseModel


class ArmMetrics(BaseModel):
    """Median metrics for one arm across runs."""

    arm: str                      # "naive" | "elliot"
    seeds_total: int
    seeds_succeeded: int
    tool_calls: int               # median total calls per run
    error_calls: int
    result_tokens: int            # median, from result_token_estimate sums
    duration_ms: int


class BenchmarkReport(BaseModel):
    spec_ref: str                 # path/URL of the OpenAPI spec
    connector_id: str
    runs: int
    seeds: list[str]              # seed ids, shared by both arms
    naive: ArmMetrics
    elliot: ArmMetrics
    transcript_ids: dict[str, list[str]]   # arm -> audit transcript ids
```

### `naive.py`

Reuse `elliot_core.openapi_analyzer.analyze_spec` — it already yields
`ProposedConnector` with per-endpoint `ProposedTool`s. Convert to a real
`ConnectorConfig` **without** any of the builder's shaping passes:

- tool id = the analyzer's proposal, unrenamed;
- description = the spec operation's `summary or description or ""`
  (exactly what generators emit);
- return fields = every response field found by
  `_extract_response_fields` (no context sizing);
- no skills, no server instructions.

This function must contain zero "make it worse" logic — assert that in the
docstring and keep it reviewable in one screen.

### `runner.py`

For each arm:

1. Load the arm's `ConnectorConfig` into the runtime executor (same entry
   point the audit prompt uses today).
2. Generate seeds once via `elliot_core.audit.seeds.generate_audit_seeds`
   (from the connector's `ProductIntent` when present, else from the spec's
   operation summaries) and reuse the same list for both arms.
3. Drive each seed with the existing audit agent loop, producing an
   `AuditTranscript` per seed (stored via `audit.store`, tagged
   `benchmark:<arm>` so `elliot_list_audit_transcripts` can filter them).
4. Score with `elliot_core.audit.judge.judge_audit`; collect per-call
   `result_token_estimate` sums and durations from the transcripts.
5. Repeat `--runs` times; take medians per arm.

Log at every boundary (`benchmark.arm.start`, `benchmark.seed.complete`,
`benchmark.report.written`) via `structlog`.

### `report.py`

Terminal output (and `report.md`, same content):

```
                       naive      elliot     delta
seeds succeeded        3/7        7/7        +4
tool calls (median)    41         19         -54%
error calls            12         1          -92%
result tokens          88 412     9 731      -89%
wall time              4m 12s     1m 38s     -61%
```

Plus a methodology section (rules above, seed list, model, run count) and
per-seed drill-down links to transcript ids. `report.json` carries
`BenchmarkReport` verbatim for the website/Cloud to render.

### CLI

`packages/core/src/elliot_core/cli.py`:

```
elliot benchmark SPEC CONNECTOR [--runs 3] [--seeds seeds.yaml] [--out DIR]
```

Exit code 0 always (it is a measurement, not a gate) — but print a
one-line summary suitable for CI logs.

## Tests

`packages/core/tests/benchmark/`:

- `test_naive.py` — petstore template spec → naive config: every endpoint
  becomes a tool, descriptions match the spec text verbatim, no field is
  dropped. Explicit test that `naive.py` never edits a description.
- `test_runner.py` — fake executor + canned transcripts: seeds are
  generated once and shared; medians computed correctly over runs;
  transcripts tagged per arm.
- `test_report.py` — golden-file test for the table and `report.json`
  round-trip; delta percentages; a naive arm that *wins* a metric renders
  honestly (no clamping deltas to "good").
- Error paths: spec that fails `analyze_spec`, connector missing, judge
  failure mid-run — all surface `ElliotError` subclasses, never bare
  exceptions.

Coverage gate: elliot-core ≥ 95% applies.

## Acceptance

- `elliot benchmark packages/core/src/elliot_core/templates/openapi-petstore.connector.json`-adjacent
  demo (petstore spec vs petstore template connector) runs end-to-end
  locally and produces the scoreboard.
- Both arms' transcripts are visible in Studio's audit views.
- The report's numbers can each be traced to a stored transcript id.
