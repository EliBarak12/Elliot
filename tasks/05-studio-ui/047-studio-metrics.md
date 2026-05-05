# 047 — Metrics Page

**Sprint**: 4 | **Estimate**: 3h | **Depends on**: 045

## Objective
Analytics dashboard powered by the audit log, fetched via MCP meta-tools.

## Files to Create

### `src/pages/MetricsPage.tsx`
Data source: `callTool('studio_get_metrics', { days: 30 })` via React Query.

Components:
- **Time series chart** (shadcn `<ChartContainer>` + recharts `<LineChart>`): tool calls per day for last 30 days
- **Tool usage bar chart**: top 10 tools by call count
- **Success rate table**: per tool — total calls, errors, success rate %, avg latency ms
- **P95 latency** badge per tool
- Date range selector (7 / 14 / 30 / 90 days) → re-fetches with updated `days` param
- "Refresh" button → invalidates React Query cache

### `src/hooks/useMetrics.ts`
```typescript
export function useMetrics(days = 30) {
  return useQuery({
    queryKey: ['metrics', days],
    queryFn: () => callTool('studio_get_metrics', { days }),
    refetchInterval: 30_000,
  });
}
```

## Done When
- [ ] Metrics page renders charts when audit log has entries
- [ ] Empty state shown with CTA when no audit entries exist
- [ ] Date range selector triggers re-fetch with correct `days` value
