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

> **Status check (2026-07): this largely exists — the gap is naming and
> surfacing, not construction.** Elliot Cloud ships the **MCP Server
> Grader**: paste any remote MCP URL on the landing page, Elliot connects
> as a real MCP client, runs 21 contract checks + live probes + an
> optional Claude agent judge, and produces a public, shareable A–F grade
> page with percentile and a copyable README badge
> (`Elliot-cloud-/docs/mcp-grading-rubric.md`, `grader-flow.md`,
> implemented in `apps/api/src/elliot_cloud/grader.py`). OSS Studio's
> Evaluation page renders the same `BEST_PRACTICES` quality scan from
> `elliot_core.eval.quality`.

One score, 0–100, per connector. Composed from things Elliot already
computes or stores:

| Component | Source (exists today) |
|---|---|
| Contract quality | linter + grader deterministic checks (shared with `elliot_core.linter`) |
| Live probe quality | grader live probes: error quality + response token cost/shape |
| Agent-judged capability | grader agent judge (Claude drives the server; 40% when run) |
| Eval pass rate | eval harness (`elliot eval`) |
| Live tool-call success rate | observation store / audit log |
| Token efficiency | tokenizer-based per-call estimates (tiktoken `cl100k_base`) |

What remains to make it *the category number*:

1. **One name.** "Grade", "quality scan", and "eval score" must all read
   **AX Score** across Studio, Cloud, README, and the grader page.
2. **Everywhere the connector is, the score is.** Connector list, publish
   flow, report page, badge — one number, same formula provenance.
3. **CI-gateable.** `elliot lint`/`eval` exit codes + a score threshold —
   the pytest-style lock-in.

Why a single number: quotable, trackable, gateable, comparable. "Our
connector is at 91" is a sentence a team lead says in standup.

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

> **Status check (2026-07): built.** The grader's public report page
> already offers "Copy README badge". The remaining work is *adoption*:
> put the badge in Elliot's own READMEs, grade well-known public MCP
> servers and (respectfully) publish the results, and make the badge the
> default close of every grader run.

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
2. **The grader as top-of-funnel (built — market it).** "Grade any MCP
   server" already runs on the Cloud landing page: public shareable A–F
   report, sign-in gate on the full audit, "build it better with Elliot"
   CTA. The funnel exists end-to-end; the work is driving traffic into it
   and adding a `uvx elliot lint` one-liner for the local-first crowd.
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

> **Correction (2026-07 audit of this doc against the code):** two claims
> below were stale, inherited from LAUNCH_READINESS.md. (1) Token counting
> is already tokenizer-based — `_estimate_tokens` in the runtime's
> session tracker uses tiktoken `cl100k_base` with a chars/4 fallback, and
> the executor sizes results against a real token budget. (2) The "free
> hosted linter" and "public report page + badge" already exist as Cloud's
> MCP Server Grader (§3.1, §3.3). The backlog below reflects what is
> actually missing. Lesson kept in writing: **re-verify LAUNCH_READINESS
> claims against code before building anything from that doc.**

Priority-ordered:

| P | Item | Why / source |
|---|---|---|
| P0 | **Say what exists.** README + website must lead with the grader, the score, and the measurable-AX positioning | The category feature is built and the public surface never mentions it. Pure legibility, zero engineering. |
| P0 | **Demo connector preloaded + first-60-seconds fix** | Verified still open: `connectors/` ships only data files, no `/welcome` flow. No legibility instrument survives an empty screen. |
| P0 | **"AX Score" naming unification** across grader grade / quality scan / eval score | §3.1 — three names for one number dilutes the category claim. |
| P1 | **Before/after benchmark harness** (naive OpenAPI-gen vs Elliot connector, same task, scored) | §3.2. The one missing instrument. Produces the hero GIF and the content engine; builds on audit transcripts + judge. |
| P1 | **Badge adoption loop** — badge in our READMEs, grade prominent public MCP servers, publish findings | §3.3 status: built, unadopted. |
| P1 | **Connector-directory + registry submissions** | Channel #1; `docs/claude-connector-directory.md` exists, execute it. |
| P2 | **Eval-in-CI recipe** (GitHub Action: lint + eval + AX-score threshold) | §5.2 — the pytest-style lock-in. |
| P2 | **Session drill-down in Studio** ("why did session X fail on tool Y") | LAUNCH_READINESS §3.4 — re-verify against current Studio before building. |
| P2 | **Per-field token attribution** (which columns cost the context) | Refines already-real token counting into design guidance. |

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

1. ~~Rewrite README hero + website copy from §8~~ (done — pass 2, same
   branch; grader surfaced on both).
2. ~~Spec AX Score v1~~ → replaced by the naming-unification item in §7:
   the score exists; unify and surface it.
3. Design the before/after benchmark harness on top of the audit judge.
4. Draft the registry/directory submission checklist and execute.
5. First-60-seconds: spec the preloaded demo connector + `/welcome` flow.
