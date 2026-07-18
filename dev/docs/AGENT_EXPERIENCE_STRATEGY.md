# Agent Experience (AX) Strategy — making the value legible

> Working document. Owns one question: **how do we make people understand the
> value of a good MCP / agent experience, and position Elliot (and Elliot
> Cloud) as the way to build it?** Companion to `PRODUCT_SPECIFICATION.md`,
> `LAUNCH_READINESS.md`, and `Elliot-cloud-/SCOPE.md`.

---

## 1. The category claim

Products won users with **UX**. They won developers with **DX**. They will win
agents with **AX** — the quality of the experience an AI agent has when it
uses your product.

This matters commercially, not just aesthetically:

- Agents are becoming a **distribution channel**. When a user's agent picks
  which CRM to query, which payment API to call, which search tool to use,
  the product the agent *succeeds with* gets the traffic.
- Agents are **repeat customers with perfect memory of failure**. A tool that
  wastes 40k tokens or returns an unrecoverable error gets routed around —
  by the agent's own planning, by the harness's tool-choice heuristics, or by
  the human who watched it fail.
- Agent traffic is **measurable in dollars**: tokens per task, retries per
  task, sessions abandoned. Bad AX is a silent cost line today and a silent
  churn line tomorrow.

**Elliot's claim: AX is a discipline, and Elliot is its workbench.** Design
the contract, size the results, structure the errors, observe every session,
prove it with evals.

## 2. Why the value is not yet legible

The honest diagnosis of why "good MCP" is a hard sell in 2026:

1. **Connecting looks solved.** Every framework can wrap an OpenAPI spec into
   an MCP server in five minutes. To a buyer, that *is* the product — until
   they watch an agent actually use it.
2. **Failure is invisible and misattributed.** When an agent picks the wrong
   tool, floods its context with a table dump, or dies on `500 Internal
   Server Error`, the user blames *the agent* ("Claude is dumb today"), not
   the product's tool surface. The product team never even finds out.
3. **There is no score.** UX has usability tests, DX has time-to-first-call,
   web perf has Lighthouse. AX has… vibes. Nobody upgrades what nobody
   measures.

So the strategy is not "explain harder." It is **make the invisible failure
visible, put a number on it, and let the contrast sell**.

## 3. Making the value legible — three proofs

### Proof by number: the AX Score
One shareable number per connector, composed from what Elliot already
measures:

| Component | Source (exists today) |
|---|---|
| Contract quality | linter grade (`elliot lint`) |
| Task success | eval pass rate (`elliot eval`) |
| Token efficiency | token estimate + observed tokens/task |
| Error recoverability | structured-error coverage, retry-success rate |
| Robustness | Petri-style audit findings (`audit_connector`) |

Ship it as a **report card** — a rendered page/badge, "Lighthouse for MCP
servers." The score is the marketing: engineers share report cards, and every
shared card teaches the category. (Elliot Cloud already has a grading rubric
and leaderboard — this is the same asset pointed outward.)

### Proof by contrast: the before/after benchmark
The single most convincing demo we can build:

1. Take a public API (e.g. the Petstore template, or a real one like GitHub).
2. Wrap it naively — auto-generated MCP from the OpenAPI spec, raw responses.
3. Build the Elliot connector for the same API — linted, sized, structured
   errors, skills.
4. Run the **same task list** through the same agent against both. Publish
   the table: tokens/task, success rate, wall time, recovery rate.

That table is the pitch deck. Every talk, README section, and landing page
leads with it. Target artifact: `dev/docs/benchmarks/naive-vs-elliot.md`
with a reproducible script.

### Proof by dollars: observability as the receipt
Studio's metrics already show tokens, latency, and errors per tool. Frame
them in cost terms: **$/task at current model pricing**, failure modes ranked
by wasted spend. "Your agents burned $114 last week retrying a tool whose
error message says nothing" is a sentence a product engineer repeats to their
manager. Observability is not a feature — it is the receipt that proves the
problem.

## 4. Stickiness — making agents stick to a product

"Sticky for agents" decomposes into mechanics we already have:

1. **Agents return to tools that work.** Harnesses and planners favour tools
   with high success and low token cost. High AX *is* the stickiness — the
   rest is instrumentation.
2. **Onboarding for agents**: the `getting_started` prompt and shipped
   skills are the agent-equivalent of a first-run wizard. An agent that is
   *taught* the product's workflows on first connect completes tasks the
   competitor's raw tool list cannot.
3. **Regression tests for AX**: eval suites guard the experience the way CI
   guards the build. A product that never regresses its agent workflows keeps
   its agent traffic.
4. **Retention analytics for agents**: the session trace is a funnel. Where
   do agent sessions drop off? Which tool call precedes abandonment? This is
   product analytics where the user is an agent.

**The stickiness loop** (this is the product story, tell it as a loop):

```
observe agent sessions → find the failure/drop-off → fix the tool contract
      ↑                                                        │
      └── agents succeed more, traffic grows ← eval guards the fix
```

## 5. Elliot Cloud — publishing the solution

**Positioning statement:**

> Elliot Cloud is where teams design, measure, and host the agent experience
> of their product — build a connector in the browser, publish it to a stable
> MCP URL, and watch every agent session that touches it.

**The ladder** (each rung feeds the next):

1. **OSS Elliot** — a solo product engineer proves it locally (`make dev`).
2. **Elliot Cloud** — their team shares one URL, one secret store, one trace
   store. This is the SCOPE.md 15-minute loop; it is also the demo script.
3. **The directory** — the published connector gets listed (Anthropic
   connector directory per `docs/claude-connector-directory.md`, the official
   MCP registry), and its AX report card becomes public proof.

**Launch-surface checklist** (each is an iteration of this loop):

- [ ] AX report card rendered per published connector (Cloud already grades —
      expose it as a public, linkable page with a badge).
- [ ] `naive-vs-elliot` benchmark published and reproducible.
- [ ] Landing narrative rewritten around AX + the stickiness loop (README
      hero, `website/index.md`, Cloud dashboard empty-states).
- [ ] Anthropic Connectors directory submission (doc exists; execute it).
- [ ] Official MCP registry listing for the hosted endpoint.
- [ ] Show HN / MCP community post led by the benchmark table, not features.
- [ ] One design-partner case study with real before/after numbers.

**Discipline:** `Elliot-cloud-/SCOPE.md` gates still bind. We do not market
past the evidence gates (≥5 active orgs, zero P0 security findings, ≥90%
tool-call success). The publishing work above *creates* the pipeline that
fills those gates; it does not replace them.

## 6. The state-of-the-art bar

"State of the art in AX tooling" — the loop stops when every row is ✅:

| Capability | Status |
|---|---|
| Agent-readiness linting with concrete principles | ✅ shipped (`elliot lint`) |
| Eval harness with token accounting | ✅ shipped (`elliot eval`) |
| Petri-style adversarial audits | ✅ shipped (`audit_connector`) |
| Full session observability (tokens, latency, errors) | ✅ shipped (Studio / Cloud observability) |
| Hosted multi-tenant publishing to a stable MCP URL | ✅ shipped (Elliot Cloud, late MVP) |
| Public, shareable AX report card / badge | ❌ missing |
| Reproducible naive-vs-Elliot benchmark | ❌ missing |
| AX-first narrative across README / website / Cloud | ⚠️ partial (AX named once in README) |
| Directory + registry listings live | ❌ missing |
| Design-partner case study with numbers | ❌ missing |

## 7. Iteration backlog (for the recurring loop)

Ordered; each firing takes the next unchecked item, or deepens the last:

1. ~~Draft the AX report-card spec~~ — first draft in
   `Elliot-cloud-/docs/POSITIONING.md` §5; deepen after the benchmark runs.
2. ~~Write the `naive-vs-elliot` benchmark plan + task list~~ — done, see
   `benchmarks/naive-vs-elliot.md`. Next: implement the runner script.
3. Rewrite the README hero + "Why Elliot" section AX-first (the loop diagram
   from §4 belongs there).
4. Draft the Connectors-directory submission from
   `docs/claude-connector-directory.md`.
5. Draft the launch post (benchmark-led).
6. Revisit §6 and re-score.
