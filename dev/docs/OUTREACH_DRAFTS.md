# Design-partner outreach — drafts

Ten emails / DMs to the design-partner shortlist from
`docs/DISTRIBUTION.md §1B`. Each one is engineered to be:

- **Under 150 words.** Founders skim. The pitch is the first line.
- **Specific to that company.** A generic "would love to chat" template
  is worse than no email. Every draft references one real thing about
  that company (their existing MCP server, a tweet, a docs page).
- **Asymmetric.** I'm offering them a working connector for their own
  product *before* I ask for anything. They evaluate code, not slides.
- **One clear ask.** Either "be a design partner" (a defined small
  commitment) or "30-minute call".

## How to use this doc

1. **Build the artifact first.** For nine of these, the email is hollow
   unless the connector exists. Build it (`elliot init` → fill in →
   lint clean → publish on Cloud or push to GitHub) before pressing send.
2. **Sequence: warm to cold.** The order below front-loads the
   founders most likely to actually reply (founder-led companies whose
   founders post their email or DM in their bio). Early replies build
   the credibility for the colder pitches.
3. **Send one per day.** Five wins back-to-back stretches your
   bandwidth; one a day forces follow-up discipline.
4. **Replace `<…>` placeholders.** Specifically: your name, your
   credibility line, the demo URL, the connector PR/link.
5. **Track in a spreadsheet** with columns: company, person, channel,
   sent date, follow-up date, response, status. Claude Cowork can
   maintain this for you — point it at the spreadsheet.

The "what to ship first" line under each email is the gating
prerequisite. Don't skip it.

---

## Tier 1 — warm founders, send first

### 1. Cal.com → Peer Richelsen

**Channel:** X DM to @peer_rich (his preferred channel; he replies to
DMs on X faster than email).
**Subject (if email instead):** Cal.com bookings as agent tools — built
the connector, want feedback.

> Hey Peer,
>
> Built a Cal.com MCP connector that any coding agent can call.
> Booking flows, event-type lookups, attendee search. The thing nobody
> else has done well: each tool returns under 200 tokens, has typed
> errors the agent can recover from, and a full trace per session — so
> when a developer asks Claude "find me a slot with Alice next Tuesday"
> the agent doesn't fail silently or burn the context window.
>
> Repo + 60-sec demo: <DEMO_URL>
>
> Asking for two things: (1) ~20 minutes of yours to tell me where the
> connector is wrong from your end, (2) permission to publish it as
> "the" Cal.com connector once you're happy with it. I'm not building
> a Cal.com competitor — Elliot is the layer above MCP that makes any
> API agent-ready.
>
> — <YOUR NAME>

**What to ship first:** A working `cal.connector.json` with at least
4 tools (`list_event_types`, `find_availability`, `create_booking`,
`get_booking`). Token cost under 200 per call on a real Cal account.

---

### 2. Trigger.dev → Matt Aitken

**Channel:** X DM to @matt_aitken.

> Matt — saw you shipped the Trigger.dev MCP server in 2025. We're
> orthogonal: Elliot lints any MCP server for the failure modes that
> burn agent context. Token cost, structured errors, replayable
> traces.
>
> Ran the Elliot linter against your trigger.dev server as a starting
> point — found three places where a Claude Code task burns ~2k tokens
> on something that could be ~300. Specifics: <LINK_TO_LINT_REPORT>.
> Not a "you're wrong" PR — just data.
>
> Two questions: (1) would you be open to a 25-minute call so I can
> understand what your users hit most often? (2) is there appetite for
> a shared "MCP authoring quality" rubric that Elliot, Trigger.dev,
> and a couple of others co-sign?
>
> — <YOUR NAME>

**What to ship first:** Public gist with the lint output of the
trigger.dev MCP server. **Soften the framing** — the gist should read
as a research finding, not a takedown.

---

### 3. Inngest → Dan Farrell

**Channel:** X DM to @dfarrell0.

> Dan — agent + workflows is two halves of the same loop. Inngest is
> async jobs and durable runs; Elliot is making any underlying API the
> agent calls *legible* — token budget per tool, typed errors, replay.
>
> I'd like to run an experiment: take one of your customers' real
> workflow patterns (the AI workflows you wrote about), instrument the
> tool-call layer with Elliot, and see whether we can measure the
> agent failing-and-retrying less. Real numbers, public write-up,
> Inngest brand-safe.
>
> 25 min next week? I'll come with a draft methodology so it's not
> "what shall we talk about."
>
> — <YOUR NAME>

**What to ship first:** A 1-pager methodology doc that the call can be
about. Lighter lift than a working Inngest connector.

---

### 4. Browserbase → Paul Klein IV

**Channel:** X DM to @pk_iv.

> Paul — Browserbase is the headless browser. Elliot is the layer that
> makes any API agent-ready. There is an obvious shared story: an
> agent driving Browserbase to scrape a site that an Elliot connector
> then exposes as a clean tool with budget + retries. End of "agent
> hits a wall trying to use a brittle scraper."
>
> Built a proof of concept: Browserbase pulls product data; Elliot
> exposes it as `search_products(q, limit)` with structured errors and
> 80-token responses. Demo: <DEMO_URL>.
>
> Two asks: (1) feedback on whether the joint story rings true for
> your customers, (2) interested in a joint blog post? I'll draft.
>
> — <YOUR NAME>

**What to ship first:** A 2-minute demo video showing Browserbase →
Elliot connector → Claude Code completing a real scraping task.

---

### 5. Composio → Soham Ganatra

**Channel:** X DM to @sohamganatra.

> Hey Soham — wanted to send this first to you because I think the
> Composio / Elliot relationship is either "we're competitive" or
> "we're complementary" and I'd rather find out from you than guess.
>
> Composio bundles 1000+ SaaS APIs as agent tools. Elliot lints any
> MCP server for token cost, structured errors, observability — and
> exposes the same connector to Claude Code / Cursor / Codex /
> OpenClaw natively. If Composio is wholesale and Elliot is the
> quality bar, we're complementary. If we converge on "the tool
> registry", we're competitive — and I'd rather know now.
>
> 20-minute call this week?
>
> — <YOUR NAME>

**What to ship first:** Nothing — this one is genuinely a positioning
conversation, and pretending otherwise reads as adversarial. Just
send.

---

## Tier 2 — medium warm, send week 2

### 6. Resend → Zeno Rocha

**Channel:** Email to zeno@resend.com (his public address) or X DM
@zenorocha. Email gets longer rope.

> Subject: A Resend MCP connector that's agent-ready (not just
> connected)
>
> Hi Zeno,
>
> I built a Resend connector for Elliot — open-source, MIT, lints
> clean on token cost and error recovery. Five tools: send email, get
> domain status, list contacts (paginated), create audience, get
> bounce reason. Each one types its errors so a Claude Code task that
> trips a rate-limit can retry intelligently instead of giving up.
>
> Repo: <REPO_URL>
>
> Resend already sponsors open source generously, so I want to be
> precise: I'm not asking for sponsorship. I'm asking for ~20 minutes
> of either yours or your DX lead's time to (a) tell me what's wrong
> with the connector from your end, (b) decide whether you'd be open
> to listing it on your docs as "community-built, agent-tested."
>
> Either way — appreciate the time.
>
> — <YOUR NAME>

**What to ship first:** Public GitHub repo
`<your-handle>/resend-elliot-connector` with the connector, a README
showing token cost per tool, and one passing eval case.

---

### 7. Neon → Heikki Linnakangas / Nikita Shamgunov

**Channel:** Email — Heikki and Nikita both have public addresses on
neon.tech/about. Pick one (Nikita for strategy, Heikki for engineering
depth).

> Subject: Neon + Elliot — your DB as agent tools in 60 seconds
>
> Hi Nikita,
>
> Elliot is an open-source platform that turns any Postgres into
> agent-ready MCP tools — verb-first descriptions, typed errors,
> token budgeting per query, replayable trace. The target user (a
> product engineer with a real DB) overlaps almost perfectly with
> Neon's.
>
> Specific co-marketing idea: a Neon project ships with an Elliot
> connector pre-wired. Spin up a Neon DB → click "Make this
> agent-ready" → get a working MCP URL that Claude Code can call.
> "From `neon create` to agent-callable in 60 seconds" — short demo
> video here: <DEMO_URL>.
>
> Would 25 minutes work next week to see if there's a real partnership
> here?
>
> — <YOUR NAME>

**What to ship first:** A scripted 60-second demo specifically using a
Neon database. Use Neon branding in the demo so they can self-evaluate
without taking the meeting.

---

### 8. PostHog → James Hawkins (or DevRel)

**Channel:** Email to james@posthog.com (his public address — confirm
on posthog.com/about before sending). If unsure, DevRel team's
posthog.com/contact-us.

> Subject: We linted your PostHog MCP server — finding worth sharing
>
> Hi James,
>
> I run Elliot, an open-source MCP quality bar — token budgeting,
> structured errors, observability for every agent call. I ran our
> linter against the PostHog MCP server you already ship, and found
> two places where a typical agent burns 4–5× more context than
> needed.
>
> Full report (concrete, no dunk): <LINT_REPORT_URL>.
>
> Two reasons I'm writing instead of just opening a PR: (1) the fixes
> are opinions, and your team should weigh them against your DX bar,
> not mine; (2) PostHog already has thoughts on agent infra — would
> love to hear them. 25 minutes?
>
> — <YOUR NAME>

**What to ship first:** The lint report itself, as a public gist or
docs page. Honest, not gotcha-y. Includes "what we agree PostHog does
better than most."

---

## Tier 3 — colder, send week 3 with the prior wins as social proof

### 9. Linear → developers@linear.app

**Channel:** Email to developers@linear.app — Linear has a
documented eng-led culture; expect a thoughtful but slow response. Do
**not** cold-DM individual engineers.

> Subject: Linear MCP — a connector that beats jerhadf's
> community one on token cost
>
> Hi Linear engineering,
>
> The community-built Linear MCP server (jerhadf/linear-mcp-server)
> is great as a proof-of-concept and the wrong shape for production
> agents — its `list_issues` tool returns ~3k tokens of context the
> agent then has to filter, where a verb-first, typed-filter version
> returns ~250.
>
> Built one with Elliot — open source, agent-tested across Claude
> Code / Cursor / Codex. Repo + side-by-side token comparison:
> <REPO_URL>.
>
> What I'd like: 30 minutes with the team to find out whether Linear
> wants this to be "the" Linear connector — happy to transfer the
> repo, happy to leave it independent. Asking before publishing
> widely so we don't fragment the ecosystem.
>
> — <YOUR NAME>

**What to ship first:** The connector, with a public side-by-side
benchmark vs. jerhadf's. Be specific about the methodology. Linear
engineering will read it carefully.

---

### 10. Supabase → kiwicopple (Paul Copplestone)

**Channel:** X DM to @kiwicopple. Supabase is too big for a generic
email to land.

> Hey Paul — Supabase already ships an MCP server. It's the "wrap
> everything" kind — surfaces every table and SQL primitive. The
> shape every actual user complains about is "the agent picks the
> wrong tool" because there are too many.
>
> Elliot is the opposite philosophy: an opinionated, lint-checked,
> token-budgeted subset for a specific use case. Built one for
> Supabase as a comparison: 8 verb-first tools that cover what 80%
> of agent users actually do. Repo + benchmark: <REPO_URL>.
>
> Not asking Supabase to drop its server. Asking if there's an
> appetite to recommend Elliot as the "production-shape MCP" for
> users building agentic products on top of Supabase data.
>
> 20 min when you can — happy with async too.
>
> — <YOUR NAME>

**What to ship first:** The Supabase Elliot connector + a public
benchmark of tool-pick accuracy: same agent, same prompts, against
the official Supabase MCP server vs. the Elliot one. This is the
table-stakes evidence that earns a kiwicopple reply.

---

## Follow-up template (use for any of the above)

Send 5 working days after the original.

> Hey <NAME> — bumping this in case the original got buried. No
> pressure if the timing's wrong; I'll assume "not now, ask again in
> 3 months" if I don't hear back, but didn't want to write you off
> after one email. <ONE NEW THING — a number, a launch, a customer
> who said yes — that wasn't in the first message.>
>
> — <YOUR NAME>

The "one new thing" rule matters. A pure ping reads as desperate. A
ping with one new specific data point reads as momentum.

---

## What you don't say, in any of these

- "Game-changer", "revolutionary", "AI-native", "next-generation".
  All red flags.
- "Quick call." Specify "20 minutes" or "25 minutes." Vague time
  estimates read as "this will be an hour".
- "Love your work." Pick one specific thing they shipped or said and
  reference it. Generic praise is worse than none.
- "Would love to learn more about you." Founders do not have time to
  educate strangers. Show that you already did the work.
- "Synergy." Ever.

---

## Realistic expected outcomes

If all 10 go well-executed:

- 3–4 will reply within a week.
- 1–2 will agree to a call.
- 1 will become a real design partner inside 30 days.

That one design partner is the goal. The SCOPE.md evidence gate is
"≥10 active installations active on 2+ days" — a single team
genuinely using Elliot internally gets you 3–5 of those installations
overnight and a feedback loop that compounds.

If the rate is much worse than 3 replies / 10 emails: the connector
artifact isn't good enough yet. Go back, sharpen the demo, retry.
That's the signal — not "outreach is broken", but "the product
isn't ready to be pitched cold yet."

---

## Tracking

Recommended spreadsheet columns:

| Company | Person | Channel | Sent | Followed-up | Replied | Status | Next action |
|---|---|---|---|---|---|---|---|

Status values: `sent` → `bumped` → `replied` → `call_scheduled` →
`call_done` → `design_partner` | `closed_lost`.

Claude Cowork can maintain this. Point it at a Google Sheet, tell it
to ping you when a Status is `replied` and a follow-up hasn't been
sent within 24 hours, and let it draft the follow-up for your review.
