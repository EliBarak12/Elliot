# Task 065 — Token Efficiency Metrics

## Goal
Surface token efficiency data across the Studio — per-tool averages, largest results, and actionable suggestions — so the developer can immediately see which tools are wasting agent context.

## Why
An agent calling a tool that returns 2,000 tokens on every call will exhaust its context window after a few turns. The developer needs to see this in Studio, not discover it by debugging agent failures.

## Backend: add efficiency endpoint

### `GET /v1/metrics/token-efficiency`

Reads from the sessions NDJSON (task 060) and returns per-tool aggregates:

```python
# In server.py
@app.get("/v1/metrics/token-efficiency")
async def token_efficiency() -> dict:
    sessions = tracker.tail(n=200)
    tool_stats: dict[str, dict] = {}

    for session in sessions:
        for event in session.get("events", []):
            if event["type"] != "tool_call" or not event.get("tool_id"):
                continue
            tid = event["tool_id"]
            if tid not in tool_stats:
                tool_stats[tid] = {"calls": 0, "total_tokens": 0, "max_tokens": 0, "errors": 0}
            tokens = event.get("result_token_estimate") or 0
            tool_stats[tid]["calls"] += 1
            tool_stats[tid]["total_tokens"] += tokens
            tool_stats[tid]["max_tokens"] = max(tool_stats[tid]["max_tokens"], tokens)
            if event.get("error"):
                tool_stats[tid]["errors"] += 1

    result = []
    for tid, stats in tool_stats.items():
        avg = stats["total_tokens"] // max(stats["calls"], 1)
        result.append({
            "tool_id": tid,
            "calls": stats["calls"],
            "avg_tokens": avg,
            "max_tokens": stats["max_tokens"],
            "error_rate": round(stats["errors"] / max(stats["calls"], 1), 3),
            "risk": "high" if avg > 1000 else ("medium" if avg > 300 else "low"),
            "suggestion": _suggest(tid, avg, stats["max_tokens"]),
        })

    result.sort(key=lambda x: x["avg_tokens"], reverse=True)
    return {"tools": result, "sessions_analysed": len(sessions)}


def _suggest(tool_id: str, avg_tokens: int, max_tokens: int) -> str | None:
    if avg_tokens > 1000:
        return f"Average {avg_tokens} tokens is very high. Add LIMIT clause or SELECT only needed columns."
    if max_tokens > 2000:
        return f"Peak {max_tokens} tokens. Add a LIMIT or pagination parameter to cap result size."
    if avg_tokens > 300:
        return f"Consider adding LIMIT or selecting fewer columns to reduce token cost."
    return None
```

## Frontend: Metrics page extension

Extend the existing `MetricsPage` (`packages/studio/src/pages/Metrics.tsx`) with a **Token Efficiency** section above the audit log table:

```
Token Efficiency                    based on last 200 sessions
───────────────────────────────────────────────────────────────────
Tool              Calls   Avg tok   Max tok   Errors   Risk
list_all           47      ████ 1,420    4,100     0%      ⛔ HIGH
list_animals       89      ░░  87       230     2%      ✓ low
get_animal         34      ░   31        45     0%      ✓ low
created_by_user    12      ░░ 210       890     8%      ⚠ med

⛔ list_all: avg 1,420 tokens is very high. Add LIMIT or select only needed columns.
⚠ created_by_user: 8% error rate. Check error handling in executor.
```

### Token risk colour

| Risk | Avg tokens | Colour |
|---|---|---|
| low | ≤ 300 | green |
| medium | 301–1000 | amber |
| high | > 1000 | red |

### Bar chart

Use a simple CSS/inline width bar (no charting library needed):

```tsx
const maxTokens = Math.max(...tools.map(t => t.avg_tokens))
<div style={{ width: `${(tool.avg_tokens / maxTokens) * 120}px` }}
     className={riskClass(tool.risk)} />
```

## Zustand additions

```ts
interface TokenEfficiencyTool {
  tool_id: string
  calls: number
  avg_tokens: number
  max_tokens: number
  error_rate: number
  risk: 'low' | 'medium' | 'high'
  suggestion: string | null
}

// Add to store:
tokenEfficiency: TokenEfficiencyTool[]
refreshTokenEfficiency: () => Promise<void>
```

## Tests

```python
def test_token_efficiency_endpoint(client, connector_file):
    resp = client.get("/v1/metrics/token-efficiency")
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    assert "sessions_analysed" in data
```

```tsx
test('shows high risk badge for expensive tool', () => {
  // msw mock returns tool with avg_tokens=1500, risk=high
  render(<MetricsPage />)
  expect(screen.getByText(/HIGH/)).toHaveClass('text-red-600')
})
```
