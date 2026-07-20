# Task 081 — Preloaded Demo Connector + Studio `/welcome`

## Goal

A brand-new user who runs the Docker one-liner lands, within 60 seconds, on
a **working connector with data**, runs a tool, and sees the call appear in
a live trace — instead of an empty dashboard with four zeros. Ship a demo
connector preloaded into an empty workspace plus a `/welcome` route in
Studio that walks the three first moves.

## Why

LAUNCH_READINESS §1 (re-verified 2026-07: still true — `connectors/`
contains only `data/` files and an eval yaml; Studio has no welcome route).
Every legibility instrument in AX_STRATEGY dies on an empty screen: no
score without tools, no trace without calls, no "aha" without data. This is
the highest-leverage remaining first-run fix.

## Implementation

### 1. The demo connector — `connectors/demo-shop.connector.json`

Use the data files that already ship in `connectors/data/`
(`customers.json`, `events.json`) as `file` sources — zero network, zero
credentials, works offline. Follow the five principles *demonstratively*
(this connector doubles as the reference example everywhere):

- `get_customer_overview(customer_id)` — cross-source JOIN (customers +
  events): the signature Elliot trick, one compact result.
- `list_recent_events(customer_id, limit)` — pagination + row caps shown.
- `search_customers(query, limit)` — search with a sized default.
- One skill (`weekly-account-review`) composing two tools, so Skills isn't
  an empty page either.
- Verb-first descriptions, typed params, described enums — it must lint
  clean with zero warnings: `elliot lint connectors/demo-shop.connector.json`
  is part of CI (see Tests).

### 2. Preload on empty workspace

`packages/mcp-plugin` workspace bootstrap (where the workspace scans
`connectors/` today):

- On startup, if the workspace contains **zero** connectors and
  `ELLIOT_PRELOAD_DEMO` is not `"false"`, copy the demo connector (and its
  `data/` files when missing) into the workspace and log
  `workspace.demo.preloaded`.
- `docker-compose.run.yml` and `.env.example` document the flag; default
  is on. `make dev` inherits the same behaviour.
- Never preload into a non-empty workspace; never re-preload after the
  user deletes it (write a `.demo-dismissed` marker next to the connector
  dir on delete).

### 3. Studio `/welcome`

`packages/studio/src/pages/WelcomePage.tsx`, routed in `App.tsx`:

- Shown when the workspace is demo-only or empty (Dashboard redirects
  there on that condition; a dismiss stores `elliot.welcome.dismissed` in
  `localStorage` and never auto-shows again).
- Three steps, each a card with a live "do it now" action — not a doc link:
  1. **Run a tool** — embedded Playground run of
     `get_customer_overview(customer_id: 1)` with the result rendered and
     its token estimate highlighted.
  2. **See the trace** — deep link to Agent Console filtered to the call
     just made ("this is what you'll see for every agent, every session").
  3. **Connect your agent** — the copyable MCP config per client
     (reuse the existing connect snippets), plus "or grade any MCP server"
     linking to the Cloud grader.
- Empty-workspace variant swaps step 1 for "create a connector" (wizard
  entry) but keeps the same three-beat structure.
- All `console.*` prefixed `[welcome]`; fetches through
  `src/client/http.ts` as required.

## Tests

- `packages/core/tests/`: lint fixture test — the demo connector lints
  with **zero errors and zero warnings** (this is the regression gate that
  keeps the flagship example exemplary).
- mcp-plugin tests: preload happens on empty workspace; skipped on
  non-empty; respects `ELLIOT_PRELOAD_DEMO=false`; respects the
  `.demo-dismissed` marker; logs the boundary event.
- Studio (`vitest`): WelcomePage renders three steps; dismiss persists;
  demo-only detection; deep-link params for Agent Console; empty-state
  variant. Studio coverage gate ≥ 70% applies.

## Acceptance

- `curl … | sh` on a clean machine → Studio opens → `/welcome` → clicking
  step 1 returns real joined data → step 2 shows the call in the Agent
  Console — under 60 seconds without reading any docs.
- Deleting the demo connector leaves no ghost state and never resurrects
  it.
- The demo connector is referenced from the README quickstart as "what
  you'll see" and used as the canonical example in docs.
