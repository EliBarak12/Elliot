# Task 064 — Studio Agent Console Page

## Goal
Add an **Agent Console** page to Elliot Studio that shows real-time agent sessions: every connection, every tool call, its parameters, result size, token estimate, and errors. This is the primary feedback loop for the connector developer.

## Why
The existing Metrics page shows individual audit entries. The Agent Console shows *sessions* — the full sequence of an agent’s interaction with the connector. This is what the developer needs to understand whether their tools are working correctly for agents.

## Page: `packages/studio/src/pages/AgentConsole.tsx`

### Layout

```
Agent Console                              ● Live  [ Refresh ]
───────────────────────────────────────────────────────────────────
▼ a3f9b1c2  claude-code  14:32:01  2 calls  118 tokens  64ms  ✓
   ├ tools/list    5 tools discovered    12ms
   ├ list_animals  {species:"dog"}   3 rows  87tok  43ms  ✓
   └ get_animal    {id:1}            1 row   31tok  21ms  ✓
───────────────────────────────────────────────────────────────────
► f7a2e001  claude-code  14:28:44  4 calls  1823 tokens  210ms  ⚠ large result
► 9c3b0d12  claude-code  14:15:02  1 call     0 tokens   12ms  ✗ error
───────────────────────────────────────────────────────────────────
⚠ Session f7a2e001: list_all returned 94 rows (1,823 tokens).
   Suggestion: add LIMIT 50 to list_animals SQL.
```

### API

Fetch from `GET /v1/sessions?n=20` (added in task 060).

### Component structure

```
AgentConsole
  SessionList
    SessionRow (collapsed by default, expandable)
      SessionHeader: id, agent, time, call count, tokens, duration, status badge
      EventList (when expanded)
        EventRow: type badge, tool name, args summary, rows, tokens, duration, error
  InsightBanner: shown when any session has a token > 500 call
    "Session X: tool Y returned Z tokens. Consider adding LIMIT."
```

### Status badges

| Condition | Badge | Color |
|---|---|---|
| No errors, all tokens ≤ 500 | ✓ | green |
| No errors, any token > 500 | ⚠ large result | yellow |
| Any error | ✗ error | red |

### Token colour coding per event

| Token estimate | Colour |
|---|---|
| ≤ 300 | green |
| 301 – 1000 | yellow |
| > 1000 | red |

### Auto-refresh

Poll `GET /v1/sessions` every 5 seconds. Show a pulsing dot indicator when live.

## Route

Add `/console` to React Router in `App.tsx`:

```tsx
<Route path="/console" element={<AgentConsole />} />
```

Add to the top navigation bar between **Metrics** and existing items.

## Zustand store additions

```ts
interface AppStore {
  // ... existing fields ...
  sessions: AgentSession[]
  refreshSessions: () => Promise<void>
}

interface AgentSession {
  session_id: string
  started_at: number
  agent_hint: string | null
  events: SessionEvent[]
  total_tool_calls: number
  total_tokens_estimated: number
  total_duration_ms: number
  error_count: number
}

interface SessionEvent {
  ts: number
  type: 'tools_list' | 'tool_call'
  tool_id: string | null
  arguments: Record<string, unknown> | null
  result_rows: number | null
  result_token_estimate: number | null
  duration_ms: number
  error: string | null
}
```

## Tests (Vitest + RTL)

```tsx
test('renders session list', () => {
  render(<AgentConsole />) // with msw mock returning 2 sessions
  expect(screen.getAllByTestId('session-row')).toHaveLength(2)
})

test('expands session on click', async () => {
  render(<AgentConsole />)
  await userEvent.click(screen.getByText('a3f9b1c2'))
  expect(screen.getByText('list_animals')).toBeInTheDocument()
})

test('shows large result warning', () => {
  // session with token > 500
  render(<AgentConsole />)
  expect(screen.getByText(/large result/i)).toBeInTheDocument()
})
```
