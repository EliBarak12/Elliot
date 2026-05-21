# Elliot — Launch Readiness & Gap Analysis

A multi-agent audit of Elliot's readiness for a public launch, covering five
dimensions: first-run UX, core feature completeness, Studio UI, production/SaaS
readiness, and competitive wow-factor. Findings are grouped by severity so the
team can sequence the work.

> Headline: Elliot is technically further along than the surface suggests. The
> Audit Judge, token-efficiency dashboard, cross-source SQL joins, and OpenAPI
> analyzer are genuinely differentiated — but the user-facing surface (first 60
> seconds, README, demo loop) does not yet *show* that. Fixing the demo loop and
> surfacing the audit/replay story will do more for adoption than any new feature.

---

## 1. First-Run UX — ~55% ready

The Docker one-liner works, but the experience stalls at an empty dashboard.

**Blockers**
- No pre-loaded demo connector. `connectors/` and `templates/` are essentially
  empty, so a new user lands on an empty Studio with no "show me it working" moment.
- Empty Studio has no next step — four stat cards reading "0" and no `/welcome` flow.
- Docker users can't run `elliot init`; the documented quickstart path is
  unreachable from the fast install path.

**Major friction**
- Quickstart lives on an external docs site, not embedded in Studio.
- The `getting_started` MCP prompt is invisible to anyone who hasn't already
  wired up an agent.
- Broken connector JSON fails silently (no error surfaced in the UI).
- Runtime startup errors are swallowed by a `catch(() => [])` in Dashboard.

---

## 2. Core Feature Completeness

| Principle | Status |
|---|---|
| Tool descriptions as contracts | Delivered — validator, linter, Pydantic models |
| Results sized for context | Partial — row caps work, but token "estimate" is `rows × 10`, not real tokenization |
| Actionable errors | Delivered — full `ElliotError` hierarchy, MCP-safe wrapping |
| Observability | Partial — structlog + SQLite store + OTel bridge, but no Prometheus, no real token cost, no Sentry |
| Platform is agentic | Partial — OpenAPI analyzer + builder tools exist, but no DB schema introspection, no live response sampling |

**Top capability gaps**
1. Token counting is heuristic, not real — agents can't budget context.
2. No DB/REST schema introspection (agents can't discover columns/response shapes).
3. Linter is advisory-only, not blocking on save.
4. No per-field token attribution.
5. OpenAPI → tools is one-way (no feedback loop from agent failures back into schema).

---

## 3. Studio UI

Surprisingly polished — shadcn/ui, Tailwind, 9 routes, SSE for live sessions,
thoughtful empty states, token-efficiency dashboard with risk levels.

**Blocking public launch**
1. No auth at all. Single-user, localhost-only. No login, API key UI, or workspaces.
2. No OpenAPI importer in the tool editor (the CLI has it; the UI doesn't).
3. No live schema preview when editing a tool.
4. Metrics → Session drill-down is missing ("why did session X fail on tool Y?").
5. Mobile untested.

---

## 4. Production / SaaS Readiness

Stronger than expected: CORS, rate limiting (slowapi + Redis), CSP, pip-audit on
CI, SSRF protection, secret redaction, read-only DB enforcement, and constant-time
API-key auth are all in place.

**Blockers for 1,000 users**
1. Single API key, no RBAC, no multi-tenancy — one key = full access to all sessions.
2. No backup/DR for SQLite/MySQL/NDJSON logs.
3. No SIGTERM handler — in-flight tool calls lost on restart.
4. No Kubernetes manifests / replica strategy.
5. Rate limit defaults to per-process in-memory — distributed deploys silently bypass it.
6. No Prometheus `/metrics`, no Sentry.
7. No privacy policy / ToS / GDPR docs (MIT license is the only legal doc).

---

## 5. Wow-Factor & Positioning

**Hidden gems being under-marketed**
- Deterministic Audit Judge scoring agent transcripts across 7 dimensions
  (`audit/judge.py`) — nobody else has this.
- Tool Quality Score (0–100) per tool.
- Token-efficiency dashboard with auto-suggestions ("Add LIMIT", "Select fewer columns").
- Cross-source SQL joins in one tool call (REST + Postgres + CSV in one result) — genuinely rare.
- Agentic builder loop (`analyze_api_spec` → `create_draft` → `lint` → `save`).

**Table-stakes gaps vs Composio / Arcade / Pipedream**
- No pre-built connector library (Stripe, Slack, GitHub, Linear, Notion).
- No OAuth flows — API keys only.
- No hosted/SaaS offering.
- No connector versioning or rollback.
- No team workspaces.

**5 wow features that would go viral (ranked by impact/effort)**
1. Tool description A/B tester — paste two descriptions, run evals, show token + success delta.
2. "Replay with fix" — from a failed session, edit the tool, rerun the exact agent prompt, see before/after.
3. Connector health scorecard — time-series of linter score, error rate, tool adoption, anomalies.
4. One-click export as Codex/Claude Code plugin (already a CLI — promote to a button).
5. Schema diff: "how agents see your tool vs. how you wrote it."

**Narrative gap**
The README sells *features* (MCP server, linter, eval). It should sell *moments* —
connect → fix → observe. Frame it as **measuring AX (Agent Experience) like you
measure UX**.

---

## The 10-item launch punch list

In priority order:

1. Ship a working demo connector preloaded on first run *(blocker)*
2. Add a `/welcome` flow in Studio when zero connectors exist *(blocker)*
3. Make the `getting_started` prompt visible without an agent attached *(major)*
4. Add real token counting — the whole pitch depends on it *(major)*
5. Add multi-user auth + workspaces *(production blocker)*
6. Wire `/metrics` (Prometheus) + Sentry *(ops)*
7. Add SIGTERM handler + document backup procedure *(ops)*
8. Build "Replay with Fix" — the single biggest wow lever *(wow)*
9. Build the A/B description tester *(wow)*
10. Rewrite the README around the three moments: connect → fix → observe *(narrative)*
