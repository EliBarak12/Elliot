# Elliot — Scope contract

A forcing-function doc. Anything that doesn't fit here doesn't ship until the
evidence demands it. Re-read before every "what if we also..." conversation.

> Status: late MVP, pre-PMF. Goal of this stage is **evidence of retention**,
> not feature breadth.

---

## 1. The one user

A **backend or full-stack engineer at a 10–200-person SaaS company** who already
has a working internal REST API or SQL database and wants their coding agent
(Claude Code, Cursor, Codex) to use it.

They share these properties:

- They have already tried wiring an MCP server by hand and hit one of: tools
  that burn 80% of the context, agents picking the wrong tool, errors that
  the agent can't recover from, no idea what the agent actually did.
- They will run something locally with Docker. They will not write Python to
  evaluate a tool.
- They care about token cost — they pay for it directly or their company does.
- They want the connector to be safe enough to point at a real (read-only)
  Postgres or a real internal API.

**Anti-personas** (interesting, but not who we're building for *now*):

- Non-technical builders. Elliot speaks "connector spec" and "MCP" today.
- Pure consumers of public MCP servers (Notion / GitHub etc.) — Elliot's
  unique value is making *your own* API agent-ready.
- Enterprise procurement. Wrong stage for a SOC 2 conversation.

## 2. The one workflow that has to work

A new user, in under **10 minutes**, can:

1. Run `curl … install.sh | sh` (one command, no toolchain).
2. Land in Studio with a **pre-loaded demo connector** that already works.
3. Point Claude Code or Cursor at it (one command, copy-pasted from Studio).
4. Ask the agent a question that uses the connector. See the tool call,
   the token cost, and the full trace in the Agent Console.
5. Edit a tool description or add a filter, save, see the agent call the new
   version on the next turn.

That loop is the product. Everything else is in support of that loop.

## 3. What Elliot does *not* do (right now)

These are deliberately off the roadmap until a critical mass of validated
users says they can't get value without them. Each carries a specific
unblocking signal.

| Not doing | Unblocked when |
|---|---|
| Adding agent harnesses beyond Claude Code / Cursor / Codex / OpenClaw | A design partner blocks adoption on a fifth harness. |
| Non-engineer onboarding wizard | We have 25 active engineer users and three say their PM is asking for it. |
| Desktop app (no Docker) | Two design partners drop off citing Docker friction. |
| Hosted connector registry / marketplace | A design partner publishes their fourth connector and asks where to share it. |
| Multi-tenant local Studio (workspaces, RBAC) | A team of 3+ engineers asks for it on the same connector. |
| Enterprise compliance posture (SOC 2, audit logs to S3, etc.) | A signed letter of intent contingent on it. |
| LLM-based "auto-fix my tool" inside Studio | The lint dashboard is in active use and users are still copy-pasting fixes by hand. |
| Real-time collaborative editing of connectors | A design partner ships a PR to add it themselves. |

## 4. Evidence gates

We move from MVP to Launch stage **only** when all three hold for a defined
two-week window:

1. **≥ 10 active installations** that ran a tool call on ≥ 2 distinct days
   in the window (`elliot kpi --window 14`).
2. **Sean Ellis ≥ 40%** — of users who answered the in-product survey, at
   least 40% would be "very disappointed" if Elliot disappeared.
3. **Median tool-call success rate ≥ 90%** on connectors that have run at
   least 20 tool calls. (If agents can't use our tools cleanly, we don't
   have product, we have a demo.)

If any of these is missing after 6 weeks of focused outreach, the right move
is to revisit the user definition above — not to add features.

## 5. False-positive list

Things that look like PMF but aren't. We do **not** count these:

- Stars on GitHub. (Stargazers do not run `tool_call`.)
- Single-session installs that never came back.
- A spike from a single blog post or HN front page without D7 retention.
- "Friends and family" usage by people in our network.
- Cloud signups that never published a connector.

## 6. Decision rules

- Before adding a feature: which of (1)–(3) under §4 does it move? If the
  answer is "none directly", it waits.
- Before adding a dependency: does it complicate Docker-only install? If
  yes, it waits.
- Before refactoring: is the surface being refactored *on* the §2 workflow?
  If no, leave it.
- Before saying yes to a partnership / integration: does it produce
  installs that satisfy the §4 evidence? Or is it brand-adjacent noise?

## 7. Review

This doc is re-read at the top of every weekly KPI review (`elliot kpi`).
If reality has moved, the doc moves with it — but in a commit, with the
reasoning written down. We do not silently expand scope.
