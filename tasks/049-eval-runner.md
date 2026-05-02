# 049 — Evaluation Runner

**Sprint**: 4 | **Estimate**: 3h | **Depends on**: 021

## Objective
Deterministic evaluation of tools: run test cases against the connector and score the results.

## Files to Create

### `packages/core/src/evaluation/runner.ts`

**`runEvalSuite(suite: EvalSuite, connector: ConnectorConfig, engine: SQLiteEngine): Promise<EvalRunResult>`**

For each `EvalCase` in `suite.cases`:
1. Call `executeTool(tool, evalCase.params, engine)` directly (no HTTP, no AI)
2. Score result against `evalCase.expectedRows` or `evalCase.expectedShape`:
   - `exact_match`: every expected row present in result (order-independent)
   - `shape_match`: result has same columns and row count
   - `contains`: result contains at least one row matching expected
3. Record: `passed: boolean`, `actualRows`, `latencyMs`, `error?`

Return `EvalRunResult`:
```typescript
{
  suiteId: string;
  runAt: string;       // ISO timestamp
  score: number;       // 0–100
  passed: number;
  failed: number;
  cases: EvalCaseResult[];
}
```

### `packages/core/src/evaluation/storage.ts`
- `saveResult(result: EvalRunResult, dir: string): Promise<void>` — write to `.elliot/eval/results/<timestamp>.json`
- `loadResults(dir: string): Promise<EvalRunResult[]>` — read all result files, sorted newest first
- `detectRegressions(prev: EvalRunResult, curr: EvalRunResult): string[]` — return case IDs that passed before but fail now

## Done When
- [ ] Suite with all-passing cases returns score of 100
- [ ] Suite with one failing case returns score < 100
- [ ] Regression detection identifies case that regressed
