# Elliot — Distribution Plan

A concrete plan for getting Elliot in front of the people most likely to use it: backend / full-stack engineers at 10–200 person SaaS companies, plus indie devs building agentic products. Drafted May 2026.

The headline pitch — refine before reusing:

> **Elliot turns your existing REST API or SQL DB into MCP tools your coding agent actually uses well.** Built-in agent-readiness lint, per-tool token budgeting, structured errors, full per-session replay. Open source, MIT. Works with Claude Code, Cursor, Codex, OpenClaw.

The implicit wedge against the current MCP-server ecosystem: most MCP servers ship as "I wrapped the OpenAPI spec" — they blow the context window, return raw tables, and surface tracebacks. Elliot makes that an anti-pattern, with tooling.

---

## 1. People to reach

Handles I verified during research are noted; ones I'm only partly sure about are flagged "(unverified)". Confirm before DMing — handles change.

### A. MCP core / Anthropic side

| Person | Role | Handle | Why they'd care | Best approach |
|---|---|---|---|---|
| **David Soria Parra** | Co-creator of MCP, Anthropic | (GitHub: @dsp-ant; X handle unverified) | Cares about MCP quality and spec evolution. Elliot's lint principles are an opinionated take on what a "good" MCP server looks like. | File an SEP or thoughtful issue on `modelcontextprotocol/modelcontextprotocol` first; then DM with a 2-paragraph framing. Don't ask for amplification; ask for spec feedback. |
| **Justin Spahr-Summers** | Co-creator of MCP, Anthropic | GitHub: @jspahrsummers | Same as above. | Same as above. |
| **Den Delimarsky** | Lead Maintainer, MCP. Anthropic. | Blog: den.dev; YouTube channel "Den Delimarsky"; X unverified — confirm before sending | Owns MCP authorization, governance, DX. Elliot's observability + structured-errors story is directly relevant to enterprise readiness, which is his stated 2026 focus. | Read his "One Year of MCP" post and reference it. Pitch a guest segment on his YouTube channel on "what makes an MCP server agent-ready." |
| **Mahesh Murag** | Applied AI Engineer, Anthropic. Public MCP advocate. | X: @MaheshMurag | Has tweeted extensively about MCP adoption and quality. Co-presented the canonical "Building Agents with MCP" workshop. | Reply (not DM) to one of his MCP-quality threads with a concrete observation from Elliot's lint output (e.g., "we linted the top 50 servers in awesome-mcp; here's what we found"). |
| **Boris Cherny** | Creator of Claude Code, Anthropic. ~260k X followers. | X: @bcherny | He sets the agent-side norms ("how Claude Code uses MCP"). Elliot reduces Claude Code's token cost on third-party APIs — measurable. | Public reply with a side-by-side: same task, naive MCP server vs. Elliot-linted server, token deltas. He retweets numerical comparisons. |
| **Jeremiah Lowin** | CEO of Prefect, creator of FastMCP (1M+ daily downloads). | X: @jlowin; GitHub: @jlowin; Bluesky: @jlowin.dev | FastMCP is the python framework many Elliot users already know. Elliot is a layer above FastMCP, not a competitor — frame as complementary. | Open a PR to FastMCP docs adding an "Agent-readiness checklist" cross-link to Elliot. Then DM. |
| **Simon Willison** | Independent. Creator of LLM CLI. Most-cited voice on MCP quirks and security. | X: @simonw; blog: simonwillison.net | He has explicitly written that he wants LLM to act as an MCP client, and has catalogued MCP security failures. Elliot's structured errors + audit log address two of his recurring complaints. | Send a short, technical email or DM with a working demo link. He blogs about anything that materially improves the LLM-tools-error story. High-value link if he posts about it. |
| **swyx (Shawn Wang)** | Editor of Latent Space; runs AI Engineer conferences. | X: @swyx | Sets the AI Engineer narrative. Latent Space has covered MCP repeatedly. | Submit to AI Engineer World's Fair CFP (deadline-watch sessionize.com/aiewf2026) — talk title proposal in §3. Email swyx@latent.space with a clean one-pager once the demo is sharp. |
| **Gergely Orosz** | Pragmatic Engineer newsletter (~1M readers, dev-tools-heavy). | X: @GergelyOrosz | Already did a "Building MCP servers in the real world" deep-dive (Dec 2025) with 46 engineers. Elliot is exactly the next-chapter "and here's how you stop making the same mistakes" story. | Email gergely@pragmaticengineer.com with a 1-paragraph framing and an offer of full access plus interviews with 3–5 Elliot design-partner engineers. He values the latter more than the former. |
| **Theo Browne (t3.gg)** | YouTube ~500k, opinionated reviews of coding agents. Built T3 Code. | X: @theo | He critiques tools when they ship and is happy to dunk on bad MCP UX. Elliot is the opposite of bad MCP UX — but only worth pitching once the Docker quickstart is genuinely "one command, opens browser, works." | Don't pitch cold. Send the demo video first, ask for honest feedback, no quote-pull request. If he likes it, the segment happens organically. |
| **Matt Pocock** | Total TypeScript; `mattpocock/skills` has ~25k stars. ~60k newsletter subs. | X: @mattpocockuk | His "skills" framework is exactly the audience Elliot needs — engineers who care about per-tool quality. There's an obvious crossover: Elliot's connector → a Pocock-style Skill that wraps it. | Open a PR to `mattpocock/skills` adding an Elliot-generated skill for a popular API (e.g., Linear). Tag him in the PR. |
| **Vasek Mlejnsky** | Co-founder/CEO E2B. | X: @mlejva | E2B is agent infrastructure, adjacent not competing. Joint demo opportunity: agent in E2B sandbox calls Elliot connector — shows full agentic loop. | DM with a working demo, propose a joint blog post. |
| **Sam Bhagwat** | Co-founder Mastra (TS agent framework, $22M Series A). | X: @calcsam | Mastra agents need tools. Elliot connectors are tools. Mastra → Elliot bridge is a one-day integration. | PR a Mastra adapter that registers an Elliot endpoint as Mastra tools; tag him. |
| **Eric Ciarla** | Co-founder Firecrawl (43k stars). | X: @ericciarla | Has done the open-source-dev-tool growth playbook well. Similar buyer (product engineer). Worth treating as a peer, not a target — swap launch notes. | Cold DM offering to swap launch playbooks. Mention his "43k stars, here's what worked" Series A post. |
| **Dev-tools VCs publicly active on X** | Sarah Guo (@saranormous, Conviction), Elad Gil (@eladgil), Guillermo Rauch (@rauchg, Vercel), Jacob Effron (@jacobeffron, Redpoint, hosts Unsupervised Learning) | n/a | They retweet interesting open-source AI infra. None invest in Elliot necessarily, but distribution-of-distribution: a Sarah Guo retweet puts you in front of every founder building agentic infra. | Don't pitch. Post the most credible artifact (the "we linted the top 50 MCP servers" piece) and tag them once with one line of context. |

### B. Companies that should be design partners

Pick on (a) their product is an obvious MCP target, (b) they have a public-facing engineering culture, (c) their staff are reachable on X / GitHub / a public Slack.

| Company | Why it's a fit | Who to reach |
|---|---|---|
| **Linear** | API-first product management. Their existing Linear MCP server (`jerhadf/linear-mcp-server`) is community-built, not officially-blessed. Elliot lets them ship one that passes their own quality bar. | Eng leadership posts on X regularly; cold-email developers@linear.app with a working Elliot-built Linear connector that beats the community one on token usage. |
| **Cal.com** | Open source, vocal founder (@peer_rich), heavily MCP-curious. Booking flows are perfect tool surfaces. | DM Peer Richelsen with a Cal.com connector demo. |
| **PostHog** | Already ships an MCP server. Their docs explicitly cover it. Likely happy to compare notes; possibly happy to recommend Elliot for customers building on top of PostHog data. | Eng / DevRel team posts publicly; James Hawkins is reachable. |
| **Trigger.dev** | Already ships an MCP server + agent rules. Same buyer as Elliot, complementary product (async jobs + tool calls). | Founder Matt Aitken (@matt_aitken) is responsive on X. |
| **Resend** | Email API, well-loved by indie devs. Obvious MCP surface (send, list, status). | Zeno Rocha (@zenorocha) — they sponsor and amplify open source heavily. |
| **Inngest** | Background jobs / workflows + AI. Their CEO Dan Farrell is publicly active. | @dfarrell0 on X. |
| **Neon** | Postgres-as-a-service. Their typical user is exactly Elliot's target — a backend engineer with a SQL DB. Obvious co-marketing: "Neon + Elliot = your DB as agent tools in 60 seconds." | Heikki Linnakangas / Nikita Shamgunov publicly active. |
| **Supabase** | Same story as Neon, much bigger community. They already have an MCP server but it's the "wrap everything" kind — Elliot is the "wrap it well" kind. | @kiwicopple is the discoverable contact. |
| **Browserbase** | Headless browser API. Already adjacent to agent stacks. Possible joint story: "Browserbase + Elliot = your scraper as an agent-ready tool with budget + retries." | Paul Klein IV (@pk_iv) reachable on X. |
| **Composio** | Bundles 1000+ SaaS APIs as agent tools. Either competitive or partner — depending on framing. Worth one conversation early to decide which it is. | Soham Ganatra (@sohamganatra) publicly active. |

---

## 2. Venues, ranked

Ranked by expected return for a 1-person launch over 30 days. Each entry: who's there, what wins, what tanks.

### Tier 1 — must-do

**1. Hacker News (Show HN)**
- *Audience fit:* very high. HN is where MCP launches break (FastMCP, every MCP server tutorial). Elliot's audience overlaps almost entirely.
- *Best time:* Tuesday or Wednesday, **8–10 AM Pacific** (peak HN). Avoid Mondays (firehose), Fridays/weekends (low traffic). One shot — bad timing = a missed launch.
- *Format:* `Show HN: Elliot – turn your REST API or SQL DB into MCP tools agents use well`. Anchor on a single, specific number ("agents use 70% fewer tokens against an Elliot-linted server vs. raw") with a live demo URL and the install command in the first paragraph. Link to the trace replay, not just the README.
- *Effort:* low to post, **very high to defend**. The author must be glued to the thread for 6–8 hours minimum, replying to every comment within 90 minutes. Sidekick-style: own your trade-offs ("yes, it's another layer; here's why"), don't hide flaws. One "fair point, fixing" reply per criticism, then go fix it.
- *Risk:* HN will reflexively ask "isn't this just FastMCP + linter?" Have the 2-sentence answer pre-written and link to a concrete diff. Also have a "compared to Composio/Pomerium/etc." paragraph ready.

**2. r/mcp (~89k members)**
- *Audience fit:* perfect. People in r/mcp are explicitly looking for MCP tooling.
- *Rules:* moderation tolerates self-promo if it's substantive. Lead with the technical artifact (a connector for a popular API, or the "we linted X servers and found Y" report), not with the product page.
- *Best post:* "I linted the top 50 servers in awesome-mcp — here's what broke." Then mention Elliot at the bottom.
- *Effort:* low. Tier 1 only because of fit.

**3. r/LocalLLaMA (~727k members)**
- *Audience fit:* medium-high. They run their own infra; Elliot's "no toolchain, just Docker" pitch resonates. They are hostile to closed-source / SaaS-first products — Elliot's MIT + Docker-first story is on-brand.
- *Rules:* hard rule against marketing. Acceptable framing: "I built this open-source thing, here are the design decisions, AMA." Never lead with the URL.
- *Best post:* a technical write-up on the agentic-builder ("we let Claude Code build a connector for the Stripe API in 4 minutes, here's the full trace, here are the linter failures we caught"). Cross-post the GitHub link as a comment, not the OP.

**4. r/ClaudeAI (~862k members)** and **r/cursor (~77k members)**
- *Audience fit:* high for Claude Code, medium for Cursor users.
- *Rules:* r/ClaudeAI is more permissive on tool posts. r/cursor is heavier on UI/UX complaints — frame Elliot as "Cursor-ready: install in one slash command."
- *Best post:* a short video showing `/plugin install elliot` and an agent using a connector you built in 60s.

**5. X / Twitter — the MCP conversation cluster**
- *Audience fit:* very high. The MCP conversation lives here, not LinkedIn.
- *Who to reply to (not DM cold):* Mahesh Murag, Boris Cherny, Jeremiah Lowin, Simon Willison, swyx, Eric Ciarla, anyone who tweets "my MCP server is too slow / too many tokens / broke."
- *Wins:* numerical before/after comparisons; short Loom videos; the lint output as an image.
- *Loses:* generic feature lists, screenshots without context, ASCII art.

**6. GitHub — awesome-mcp lists and adjacent issues**
- *Where:* `wong2/awesome-mcp-servers`, `punkpeye/awesome-mcp-servers`, `appcypher/awesome-mcp-servers`, `modelcontextprotocol/servers` (only if they accept third-party submissions; check `CONTRIBUTING.md`).
- *Approach:* one clean PR per list, properly categorised, with a 1-line description that's not hype.
- *Bonus:* search GitHub Issues for "MCP token cost", "MCP server too verbose", "structured errors MCP". Reply *only* if you have a working answer — link to a specific Elliot doc, not to the homepage.

**7. Discord — three specific servers, in order**
1. **MCP community Discord** (Frank Fiegel / punkpeye runs the de-facto MCP community server; invite is linked from his GitHub `punkpeye/awesome-mcp-servers`). Most fit, smallest noise.
2. **Latent Space Discord** (invite: `discord.gg/xJJMRaWCRt`, per latent.space/p/community). Cross-section of AI engineers.
3. **Cursor Discord** (`discord.gg/cursor`, ~36k members) and **Claude Discord** (`discord.com/invite/6PPFFzqPDZ`). Useful for support replies to people asking "how do I add my own MCP server."
- *Rule for all four:* never drop a link cold. Hang out, answer a couple of questions, then post in the channel that exists for showing what you're building (usually #showcase or #share-what-you-made).

### Tier 2 — high-leverage but slower

**8. AI Tinkerers meetups (220 cities, 106k members)**
- *Audience fit:* perfect — the format is "live demo, working code, no slides," which is exactly Elliot's strength.
- *How:* apply to demo at SF, NYC, or your home city. The screening expects something working you can show in 5 minutes. The agentic-builder demo (agent builds a connector live) is the obvious pick.
- *URL:* aitinkerers.org/all_cities

**9. Newsletters — submit / pitch in priority order**
- *Latent Space* (swyx — see above). Tier 1 if accepted; takes 4–6 weeks lead time.
- *The Pragmatic Engineer* (Gergely Orosz). Long-form deep-dive about Elliot's "five principles" as a critique of current MCP design fits his MCP-deepdive series.
- *Ben's Bites* (~120k subs, founder-centric, casual tone — submit via bensbites.com submission form).
- *TLDR AI* (~920k subs, daily, technical — submit at tldr.tech/ai/submit-a-news-story).
- *The Rundown AI* (~1.75M readers, broader audience — lowest fit, highest reach; consider only after the others have hit).
- *Heavybit's "Open Source Ready" podcast* (Den Delimarsky was a recent guest) — a natural fit for the open-source-dev-tools founder narrative.
- *No Priors* (Sarah Guo / Elad Gil) — only after you have ARR or 1k+ GitHub stars; they want a "moment," not an intro.

**10. Podcasts to pitch (in fit order)**
- *Latent Space podcast* (swyx + Alessio).
- *Software Engineering Daily* — they did the FastMCP episode; would likely take the "Elliot fixes what MCP servers get wrong" angle.
- *DevTools FM* (devtools.fm) — they did Steve Krouse / Val Town; small audience but exactly the right people.
- *Scaling DevTools* (scalingdevtools.com) — same.
- *Open Source Ready* (Heavybit).
- *Generationship* (Heavybit, did Simon Willison) — broader AI audience.

**11. Conferences / CFPs — file these now**
- **AI Engineer World's Fair 2026** — June 29–Jul 2, San Francisco. CFP at sessionize.com/aiewf2026. Tracks include MCP/observability adjacent. Best talk fit: "Five principles for MCP servers agents can actually use" or a live agentic-builder demo. Lightning talk (5–10 min) is the easiest in.
- **AI Engineer Code Summit** — November 2026, invitation only. Get on swyx's radar via the newsletter / podcast first, then this is reachable.
- **MCP Dev Summit / AGNTCon + MCPCon** (Linux Foundation, Agentic AI Foundation). The April 2026 NYC one already happened (~1,200 attendees). Next: AGNTCon + MCPCon Europe, **Sept 17–18 2026 (Amsterdam)** and **AGNTCon + MCPCon North America, Oct 22–23 2026 (San Jose)**. CFPs: events.linuxfoundation.org — file as soon as they open.
- **AI Engineer Europe 2026** — April 8–10, London (this one is past or imminent depending on read-date; check ai.engineer/europe/2026).

### Tier 3 — situational

**12. LinkedIn**
- *Useful only* for the SaaS engineering-manager buyer at the 50–200-person company. Not where indie devs / open-source contributors hang out.
- *Best post type:* "we cut our agent token bill in half" case study, ideally with a co-author from a design-partner company.
- *Worth one post per design-partner win;* not worth ongoing posting.

**13. dev.to / Hashnode / Medium**
- Useful as long-form anchor content that HN/Reddit posts link *to*. Don't bother with them as primary distribution.

**14. YouTube — sponsorships, not viral**
- The relevant creators (Theo, Fireship, ThePrimeagen, Yacine, Jason Goecke, Mahesh's own talks) don't take sponsorships for early-stage OSS — they cover it organically when it's interesting.
- *Better play:* short, well-cut demo videos (3–5 min) hosted on YouTube but distributed on X. The 30-second agentic-builder loop is the canonical artifact.

---

## 3. Content artifacts that earn attention

Five to seven. Each: title, hook, target audience, where it goes, and what success looks like.

**1. "We linted the top 50 MCP servers on awesome-mcp. Here's what broke."**
- *Hook:* numerical, scoreboard-style, name servers. Anonymize politely if needed — but real numbers.
- *Audience:* MCP authors, agent builders, anyone who's wondered why their MCP context is so big.
- *Channels:* HN front page candidate. r/mcp top of week. X thread (10 tweets). swyx will retweet a credible version.
- *Success:* 200+ HN upvotes; cited in a Latent Space / Pragmatic Engineer issue within 60 days.

**2. "Agent builds its own Stripe connector in 4 minutes — full trace"**
- *Hook:* 3-minute Loom of Claude Code (or Codex) using Elliot's agentic-builder to scaffold, lint, eval, and ship a Stripe connector. Real Stripe sandbox. Real tool calls in Studio.
- *Audience:* the agent-curious product engineer at every SaaS company.
- *Channels:* X (primary), YouTube (canonical link), r/ClaudeAI, r/cursor.
- *Success:* the video is the most-linked Elliot artifact for 90 days.

**3. "Why your MCP server is burning 80% of your agent's context (and how to fix it)"**
- *Hook:* a blog post that picks one popular MCP server (with permission, ideally), shows a real conversation, computes the token waste, and walks through the four lint principles.
- *Audience:* developers building MCP servers — explicitly the "I shipped one in a weekend" crowd.
- *Channels:* blog → HN as `Show HN` companion piece. Crosspost to dev.to with a "Discussion at HN" link.
- *Success:* the canonical "what makes an MCP server good" post; cited in MCP spec discussions.

**4. "Inside Elliot Studio: replaying an agent session that almost dropped a table"**
- *Hook:* short screen-recorded post where the trace shows an agent making a destructive call, the structured error catches it, and the replay lets you debug. Real, scary, recoverable.
- *Audience:* engineering managers / staff engineers worried about agent safety. LinkedIn-friendly.
- *Channels:* LinkedIn, X, hugops-adjacent corners of HN.
- *Success:* surfaces the audit-log story (the part most MCP demos don't have).

**5. "We turned the entire PostHog (or Linear) API into 12 well-typed MCP tools — and here's the eval suite"**
- *Hook:* a real connector for a product the audience uses every day, with the eval cases public. Ideally cross-published with PostHog or Linear themselves.
- *Audience:* people who use that product. Doubles as marketing for both sides.
- *Channels:* joint blog, X thread from both accounts, GitHub repo as standalone plugin (`elliot export-plugin posthog.connector.json`).
- *Success:* the connector itself gets traction independent of Elliot — and brings users back.

**6. "Five principles for tools agents actually use"**
- *Hook:* a manifesto-style piece. Short. Quotable. Maps directly to the five lint rules. Borrows from the Joel-on-Software / Rich Hickey rhetorical mode.
- *Audience:* the engineer who wants something to share in their team Slack.
- *Channels:* docs page (canonical) + a HN-friendly version. Tweet-thread version.
- *Success:* enters the vocabulary; people start saying "is your tool agent-ready?"

**7. "MCP server token-cost benchmark: 10 popular servers, same agent task"**
- *Hook:* a public benchmark, methodology open-sourced. Update quarterly.
- *Audience:* anyone running MCP in production.
- *Channels:* GitHub repo (separate from main Elliot repo, so it lives as a community asset). Update tweet quarterly.
- *Success:* becomes the cited number in MCP debates.

---

## 4. Earn-our-way-in plays (compounding, patient)

**1. Contribute to the MCP spec.**
File a thoughtful SEP about token-budget metadata in tool descriptions, or about structured-error shape. Doesn't matter if it lands — being in the discussion is the point. Den Delimarsky and the maintainer team read every SEP.

**2. Sponsor one small, exactly-on-target newsletter or podcast.**
Not TLDR. Not Ben's Bites. Pick *AI Engineer Pack* if it accepts sponsors, *DevTools FM*, or *Scaling DevTools*. Budget: $500–$2,000 a slot, four slots over the launch window. The audience is 5,000 people but they're the right 5,000.

**3. Ship 5–10 polished standalone connector plugins for popular products.**
Linear, Stripe, PostHog, Resend, Cal.com, Supabase, GitHub, Notion, Slack, Sentry. Each as a standalone repo using `elliot export-plugin`. Each repo links back to Elliot in the README. The plugins compound: each one is a search-result for that product's name + MCP, and each one demos Elliot's lint quality on a real API.

**4. Partner with one agent vendor for a co-launch.**
Not Anthropic — too slow, too crowded. Cursor or OpenClaw is the right target. Pitch: "Elliot is the default 'bring your own API' story for Cursor users." A featured slot in their plugin marketplace + a joint blog is worth more than any single post you can make.

**5. Run a public quarterly "MCP server quality report."**
Same benchmark format every quarter, scored consistently, with named servers. After 2–3 quarters this becomes a citable artifact that other people link to. Owns a category.

**6. Sponsor or co-host one AI Tinkerers night.**
Hosting in SF or NYC costs ~$3–8k and puts Elliot in front of 80–150 of exactly the right people — and on the recap email to 100k+ subscribers.

**7. Open-source contribution playbook: contribute one well-scoped PR to FastMCP, one to a major awesome-mcp list, one to PostHog's MCP server.**
Each PR builds reputational standing with a maintainer who can later signal-boost.

---

## 5. Four-week launch sequence

The premise: Week 4 is the HN Show HN day. Everything before is loading.

### Week 1 — load the canon
- [ ] Finalize the Docker quickstart so `curl … | sh` truly works first-time on a clean Mac and Linux VM. Test on 3 machines.
- [ ] Record the 3-minute "agent builds a Stripe connector" video. Host on YouTube unlisted.
- [ ] Write the "five principles" manifesto post. Publish on the docs site. Don't promote yet.
- [ ] Build connectors for **Linear**, **PostHog**, **Resend**, **Stripe**, **Cal.com**. Export each as a standalone plugin repo. Get each to a state you'd be proud to show that company's CTO.
- [ ] Submit Elliot to `wong2/awesome-mcp-servers`, `punkpeye/awesome-mcp-servers`, `appcypher/awesome-mcp-servers` via clean PRs.
- [ ] Join: MCP Discord, Latent Space Discord, Cursor Discord, Claude Discord, r/mcp, r/LocalLLaMA, r/ClaudeAI, r/cursor. Read for one week before posting anything.
- [ ] Open a thoughtful issue or SEP on `modelcontextprotocol/modelcontextprotocol` about token-budget metadata. Cite Anthropic's "code execution with MCP" engineering post for context.

### Week 2 — seed the conversation
- [ ] Publish the "We linted the top 50 MCP servers" report. Post to r/mcp first. Then X thread. Hold HN.
- [ ] Reply (substantively, with data) to 5+ ongoing X threads about MCP costs or quality. Mahesh Murag and Simon Willison thread regularly.
- [ ] Pitch swyx (latent.space), Gergely (pragmaticengineer.com), Den Delimarsky (heavybit OSReady), and Heavybit's Scaling DevTools podcast — short emails, link to the demo video and the lint report.
- [ ] PR a Mastra adapter for Elliot. Tag @calcsam.
- [ ] PR a skill into `mattpocock/skills` built off an Elliot connector. Tag @mattpocockuk.
- [ ] Reach out to design-partner candidates: DM Peer Richelsen (Cal.com), Matt Aitken (Trigger.dev), Eric Ciarla (Firecrawl), James Hawkins (PostHog), Zeno Rocha (Resend). Frame: "we built this against your API, want to look?"
- [ ] Apply to demo at the next AI Tinkerers night in your home city.

### Week 3 — pre-launch warming
- [ ] Publish "Why your MCP server is burning 80% of your agent's context" on the blog.
- [ ] Publish the joint Linear or PostHog post (whichever partner says yes first).
- [ ] Run a public benchmark drop: "MCP server token-cost benchmark v1" — repo, methodology, numbers. Tweet, post r/mcp.
- [ ] Pre-brief: send the HN post draft and a private demo link to 5–10 friendly engineers (your design partners, anyone who replied positively to Week 2 outreach). Ask if they'll upvote and comment substantively in the first hour — *not* a vote ring; you want their actual technical questions in the thread.
- [ ] Submit talk to AI Engineer World's Fair CFP (sessionize.com/aiewf2026). Submit to AGNTCon + MCPCon Europe / NA CFPs.
- [ ] Pitch TLDR AI and Ben's Bites for week-4 inclusion (their lead times are days, not weeks).

### Week 4 — launch
- [ ] **Tuesday or Wednesday, 8:30 AM PT:** `Show HN: Elliot – turn your REST API or SQL DB into MCP tools agents use well`. Anchor on a single number. Link to the live demo + a 3-minute video + the install command in para 1.
- [ ] Be at the keyboard for 8 hours minimum. Reply to every comment within 90 minutes for the first 4 hours. Own trade-offs honestly.
- [ ] Within an hour of HN: post to r/mcp (link the HN thread, write 3 fresh paragraphs for context). 4 hours later: r/LocalLLaMA with a different framing (technical depth, not promo). Next day: r/ClaudeAI and r/cursor with the demo video as the OP.
- [ ] X launch thread: 6–10 tweets, one image per tweet. First tweet is the headline + number + Loom link. Pin to profile.
- [ ] Email update to anyone who replied during Weeks 2–3: "we're live, here's the post." Ask for honest amplification — not vote-rigging.
- [ ] Post to Latent Space Discord #showcase and MCP Discord #show-and-tell.
- [ ] LinkedIn: one post with the "agent almost dropped a table" trace screenshot.
- [ ] Within 48 hours: write the "what we learned launching" follow-up post. Reply to every issue filed on the repo personally.

### Beyond week 4 — the second wind
- [ ] Day 14 post-launch: ship a connector for whichever product was most-requested in launch comments. Tweet at the company.
- [ ] Day 30: quarterly MCP quality report v2.
- [ ] Day 45: confirm AI Engineer World's Fair talk acceptance, start prep.
- [ ] Day 60: pitch No Priors / Latent Space podcast with launch numbers in hand.

---

## Calibration notes

- **What I'm sure about:** the conference dates (AIEWF June 29–Jul 2, AGNTCon EU Sept 17–18 Amsterdam, NA Oct 22–23 San Jose), the subreddit names and approximate sizes, the major newsletters and their approximate reach, the named people's roles, the FastMCP / Den / Boris / Mahesh / Jeremiah connections, the official MCP creator names.
- **What to verify before acting:** specific X handles I flagged "unverified" (mainly David Soria Parra and Den Delimarsky's X). The Frank Fiegel MCP Discord invite URL — get it from his current `awesome-mcp-servers` README. Newsletter submission URLs (these change). The exact Latent Space Discord invite (the one I cited works as of the latest cache but the canonical invite is always linked from latent.space/p/community).
- **What I deliberately *didn't* include:** ProductHunt (low fit for dev tools in 2026 — see the consistent ProductHunt-skepticism in HN comments about dev launches). YC Demo Day / YC company directory (Elliot isn't YC). Generic "post on Indie Hackers" (audience overlap is real but small).
- **The hardest part of this plan is week 4, hour 0–8.** Everything before is preparation; the HN launch is where you either get 200 upvotes or 20. Don't post until the Docker quickstart genuinely works first-time and the demo video is genuinely good. A delayed launch is recoverable; a fumbled launch isn't.

---

*Last updated: May 2026.*
