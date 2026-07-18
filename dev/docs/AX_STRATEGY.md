# Elliot — Agent Experience (AX) Product Strategy

> How we make the value of good MCP / agent experience legible, make agents
> *stick* to products built with Elliot, and publish Elliot Cloud as the
> category solution. Companion to `SCOPE.md`, `LAUNCH_READINESS.md`, and
> `agentic-product-design.md`. This is the positioning source of truth;
> product docs describe *what* Elliot is, this doc describes *why anyone
> should care* and how we prove it.

---

## 1. The thesis in one sentence

**Everyone can generate an MCP server now. Almost nobody can prove theirs is
good. Elliot is the platform that makes agent experience measurable — and
then makes it excellent.**

The tagline that survives every draft:

> **"They get you an MCP server. Elliot makes agents succeed with it."**

## 2. The market moment (July 2026)

The facts that make this the right wedge at the right time:

- **MCP won.** Donated to the Linux Foundation end of 2025; ~10,000 public
  servers in the official registry; 97M+ monthly SDK downloads; adopted by
  ChatGPT, Cursor, Gemini, Copilot, and VS Code. Roughly 41% of surveyed
  software orgs have MCP servers in limited-or-broad production
  (Stacklok 2026).
- **Quality did not.** A 2026 Queen's University study of 856 tools across
  103 MCP servers found **97.1% of tool descriptions have at least one
  quality issue, and 56% fail to state their purpose clearly.** The average
  MCP server is a liability the owner cannot see.
- **AX is now a named discipline.** "Agent Experience" (coined by Netlify's
  CEO, Jan 2025) has a community site (agentexperience.ax), O'Reilly
  coverage, and vendor content from Speakeasy and Arcade. The market has
  the vocabulary; nobody owns the *measurement*.
- **Generation is commoditizing.** Speakeasy/Gram, Stainless, Postman, and
  Composio all turn an OpenAPI spec into an MCP server in minutes.
  When creation is free, *quality is the product*.

The gap between "has an MCP server" (everyone, soon) and "agents actually
succeed with it" (almost no one, measurably) is Elliot's entire market.

## 3. Why people don't get the value yet — and the fix

The problem is not the product; it is **legibility**. Bad AX is invisible to
the product owner: the agent silently burns tokens, retries in circles, or
answers wrong, in someone else's chat window. No one files a bug that says
"your tool description made Claude pick the wrong tool."

So the pitch "we make your tools agent-ready" lands as abstract hygiene —
like being told to floss. The fix is to **show the delta, in numbers, in
under 60 seconds**. Three legibility instruments, in priority order:

### 3.1 The AX Score — the number that creates the category

One score, 0–100, per connector. Composed from things Elliot already
computes or stores:

| Component | Source (exists today) |
|---|---|
| Contract quality | linter findings (`elliot lint`) |
| Eval pass rate | eval harness (`elliot eval`) |
| Live tool-call success rate | observation store / audit log |
| Token efficiency | token estimates per call (needs real tokenization — see §7) |
| Error recoverability | structured-error coverage + retry-loop detection in traces |

Why a single number: it is quotable, trackable, gateable in CI, and
comparable across teams. "Our connector is at 91" is a sentence a team lead
says in standup. FICO for agent-readiness. The lint/eval/observe machinery
is Elliot's moat; the score is its marketing surface.

### 3.2 The before/after demo — the money demo

Take a real OpenAPI spec. Run the same agent task twice against:

1. the naive auto-generated MCP server (what every generator ships), and
2. the Elliot-shaped connector (verb-first tools, sized results, structured
   errors).

Show side-by-side: **tool calls, tokens, wall time, success**. This is the
GIF at the top of the README, the first 30 seconds of every demo, and the
landing-page hero. It converts "agent-ready" from adjective to arithmetic.
(Petri-style audit transcripts already give us the raw material.)

### 3.3 The public badge — the viral loop

`![AX Score: 91](…)` — a README/registry badge, like coverage badges, backed
by a public per-connector report page on Elliot Cloud (score, tool list,
token profile; no private data). Every badge on someone else's README is an
Elliot ad placed by a happy user. Coverage badges built Codecov; AX badges
can build Elliot.

## 4. Category and positioning

**Category we claim: the Agent Experience (AX) platform.** We do not invent
the term — we operationalize it. The line in the README already says it:
"AX is to agents what UX is to users. Elliot's job is to make AX
measurable." That is the category claim; every surface should repeat it.

### Competitive map

| Player | What they sell | What they don't |
|---|---|---|
| Speakeasy / Gram | OpenAPI → MCP generation + hosting | No quality score, no evals, no session-level agent observability |
| Stainless | SDK-first MCP generation | Same — quality is assumed, not measured |
| Composio | 500+ managed catalog integrations | Can't bring your own proprietary API without their team |
| Arcade | MCP runtime, per-user OAuth, governance | Access control ≠ agent success; no design/eval loop |
| Smithery / registries | Distribution | Listing ≠ working |

Every competitor's pitch ends at "you have an MCP server / it's governed."
Elliot's pitch starts there: **design → lint → eval → audit → publish →
observe → improve** is a loop nobody else closes, and each pass around the
loop raises a number everyone can see.

Positioning statement: *For product engineers whose users are increasingly
agents, Elliot is the AX platform that turns any API or database into MCP
tools agents measurably succeed with — unlike generators and gateways,
which stop at "connected," Elliot proves "working" with lint, evals, live
traces, and an AX score.*

## 5. Stickiness — two loops, deliberately built

"Make agents stick to their products" decomposes into two distinct loops:

### 5.1 Agents stick to the *product* (our user's win)

An agent "prefers" a product the way water prefers downhill: it repeats
what succeeds cheaply. Concretely, agents return to tools that:

1. get picked correctly (precise, verb-first contracts),
2. succeed first try (typed params, coercion, good defaults),
3. cost few tokens (sized results — the agent can afford to call again),
4. fail recoverably (structured errors that say what to do next),
5. teach workflows (skills / MCP prompts that encode multi-step jobs), and
6. improve over time (the `submit_feedback` tool lets the agent itself
   file friction reports — the product literally learns from its agent
   users).

Items 1–4 are the five principles; items 5–6 are the underrated stickiness
features and deserve louder marketing. **A product with skills + feedback
is not just callable, it is *habitable* — the agent's session gets better
the longer it stays.** That's the retention story our users buy.

### 5.2 Teams stick to *Elliot* (our win)

- **Traces are gravity.** Weeks of session history, token analytics, and
  audit transcripts live in Elliot's observation store. The debugging
  workflow ("why did the agent fail on tool X for customer Y?") only
  exists here.
- **Evals are regression tests.** Once eval suites gate a team's CI
  (`elliot eval` + AX-score threshold), Elliot is in the deploy path —
  the same lock-in pytest has.
- **The published URL is in every client.** Each teammate's Claude
  Code/Cursor/Codex config points at the Cloud connector URL. Ripping
  Elliot out means touching every seat.
- **The AX score is the team's public number.** Nobody deletes the thing
  their badge points at.

Note the alignment: everything that locks teams in also genuinely makes
their agents succeed more. Stickiness by value, not by hostage-taking.

## 6. Publishing Elliot Cloud as *the* solution

Cloud's `SCOPE.md` already nails the wedge (2–5 person team, 15-minute
loop, ten safe tenants). This section adds the go-to-market on top.

### Messaging ladder

1. **Hook (the fear):** "97% of MCP tools have a defect their owners can't
   see. Is yours one of them?"
2. **Instrument (the demo):** before/after run + AX score on *their* spec —
   `elliot lint` on any OpenAPI file is the free taste.
3. **Product (the loop):** design → lint → eval → publish to a stable MCP
   URL → observe every session.
4. **Outcome (the story):** "Agents pick your product, succeed with it,
   and come back. You can watch it happen."

### Channels, in order of expected yield

1. **Registry + directory presence.** Official MCP registry listing,
   Anthropic connector-directory submission (`docs/claude-connector-directory.md`
   is already written — execute it), PulseMCP/Smithery listings. Meet
   agents (and their humans) where they already shop.
2. **The free linter as top-of-funnel.** "Score any OpenAPI spec's
   agent-readiness" — a web form on elliot-cloud.com and a `uvx elliot lint`
   one-liner. Cheap to run, produces a shareable number, ends with
   "publish the fixed version on Elliot Cloud."
3. **AX content with receipts.** We hold real cross-connector data
   (token profiles, failure taxonomies, retry loops). Publish "State of
   agent tool quality" findings the way Speakeasy publishes AX think
   pieces — except ours have measurements. Target agentexperience.ax,
   HN, and the MCP community channels.
4. **Badges** (§3.3) as the compounding loop.

### Pricing posture (sketch, not commitment)

- **OSS:** everything local, forever free — the trust anchor.
- **Cloud Free:** 1 workspace, 2 published connectors, 14-day trace
  retention — enough to feel the loop.
- **Cloud Team (~$49–99/seat-adjacent):** more connectors, 90-day
  retention, eval CI integration, badges/report pages.
- **Later:** usage-based on tool calls once §SCOPE evidence gates pass.
  Do not design billing before ten teams are active (per SCOPE.md).

### What "published as the solution" means, checkably

- Elliot Cloud is listed in the official MCP registry and submitted to the
  Anthropic connector directory.
- The landing page leads with the before/after demo and a live AX-score
  widget.
- Five external orgs meet the SCOPE.md activity gate; at least three
  display an AX badge publicly.
- "Elliot" appears in a third-party MCP-hosting comparison (Vayro-style)
  in the *quality/observability* column no one else fills.

## 7. Product backlog implied by this strategy

Priority-ordered; items marked ⚠ are prerequisites for honest marketing —
we cannot sell measurement while the measurement is fake.

| P | Item | Why / source |
|---|---|---|
| P0 ⚠ | **Real token counting** (tokenizer-based, per call, per field) | Today's estimate is `rows × 10` (LAUNCH_READINESS §2). Every pitch above quotes tokens; the number must be real. |
| P0 | **AX Score v1** (lint + eval + live success + tokens, per connector, in Studio & Cloud) | §3.1. The category-defining number. |
| P0 | **Demo connector preloaded + first-60-seconds fix** | LAUNCH_READINESS §1: new users land on an empty dashboard. No legibility instrument survives an empty screen. |
| P1 | **Before/after benchmark harness** (naive OpenAPI-gen vs Elliot connector, same task, scored) | §3.2. Produces the hero GIF and the content engine. Builds on audit transcripts + judge. |
| P1 | **Public report page + AX badge on Cloud** | §3.3. Needs Cloud publish + a public read-only route. |
| P1 | **Connector-directory + registry submissions** | Channel #1; the doc exists, execute it. |
| P2 | **Session drill-down in Studio** ("why did session X fail on tool Y") | LAUNCH_READINESS §3.4; the observability story's missing click. |
| P2 | **Eval-in-CI recipe** (GitHub Action: lint + eval + AX threshold) | §5.2 — the pytest-style lock-in. |
| P2 | **Free hosted linter** (paste an OpenAPI spec → score) | Channel #2 top-of-funnel. |

## 8. Messaging kit (for reuse in README, website, launch posts)

- **One-liner:** Elliot turns any API or database into MCP tools agents
  measurably succeed with.
- **Category line:** AX is to agents what UX is to users — Elliot makes AX
  measurable.
- **Competitive line:** Generators get you an MCP server. Elliot makes
  agents succeed with it.
- **Fear line:** 97% of MCP tool descriptions have a defect their owners
  can't see.
- **Stickiness line:** Agents return to products where they succeed.
  Elliot makes your product that product.
- **Cloud line:** Build it in the browser, publish it at a URL, watch
  every agent session — no Docker, no toolchain.

Objection handling:

- *"I already generated an MCP server from my spec."* — Great, that's step
  one. Lint it; the average server has defects in 97% of tools. Elliot
  tells you which, fixes the loop, and proves the improvement.
- *"Why not just Composio/Arcade?"* — Catalogs and gateways solve access
  and governance for *known* SaaS tools. Your own product's AX — whether
  agents succeed with *your* API — is exactly what they don't measure.
- *"Agents work fine with my API already."* — How do you know? (This one
  usually closes the demo.)

## 9. How this document evolves

Owned by the product-value loop. Each revision must keep §7 in sync with
LAUNCH_READINESS.md and SCOPE.md evidence gates. Next planned passes:

1. Rewrite README hero + website copy from §8 (make the public surface say
   what this doc says).
2. Spec AX Score v1 (formula, weights, API, Studio/Cloud UI) as a task file.
3. Design the before/after benchmark harness on top of the audit judge.
4. Draft the registry/directory submission checklist and execute.
