# Elliot demos

Five demos in five different formats, each engineered around one of Elliot's
real differentiators. Every demo lists: the audience, the hook, the script
(timed), the commands to run, the visual the viewer sees, and the call to
action. Built to be recorded as Loom / asciinema / a Twitter clip without
further design work.

> Rules of thumb the demos below follow:
> - Open with the problem, not the product. Show pain in the first 10 seconds.
> - Show a real terminal / real Studio — never a mock.
> - Cap each demo at 90 seconds. Use cuts.
> - Always end on a specific URL or command the viewer can copy.

---

## Demo 1 — "Postgres → MCP in 90 seconds"

**Audience:** backend engineers on r/Postgres, r/LocalLLaMA, Show HN.
**Hook:** "Your Postgres, agent-ready, in one command. No Python, no
prompts, no MCP-server boilerplate."
**Format:** asciinema → 90s GIF for the README + tweet.

### Script
| t | What you say | What's on screen |
|---|---|---|
| 0:00 | "Here's a fresh Postgres with the dvdrental sample." | `psql` listing 15 tables |
| 0:08 | "I want Claude Code to query it. The bad path: spend a weekend writing an MCP server." | (silence on the bad path — just close the tab) |
| 0:15 | "The Elliot path is one command." | `curl … install.sh \| sh` |
| 0:35 | "Studio opens. The pre-loaded demo connector is already wired to my Postgres." | Studio → Sources → green dot |
| 0:45 | "I'll add a tool: 'list films by category, sized for context.'" | Click Tools → New → fill 3 fields |
| 1:05 | "Save. Switch to Claude Code." | terminal: `claude` |
| 1:10 | "Ask the agent." | "show me the 5 highest-grossing comedy rentals" |
| 1:25 | "It picks the tool, gets back ~80 tokens of structured rows, answers." | Studio Agent Console: live trace pops in |
| 1:30 | "Trace, tokens, latency — visible. That's the loop." | (end card: github.com/EliBarak12/Elliot) |

### Recording commands
```bash
docker run -d --name pg-demo -e POSTGRES_PASSWORD=demo -p 5432:5432 \
    postgres:16
# load sample data (5s, voice over)
psql -h localhost -U postgres -f scripts/dvdrental.sql

# the demo proper
curl -LsSf https://raw.githubusercontent.com/EliBarak12/Elliot/main/scripts/install.sh | sh
```

---

## Demo 2 — "Why your MCP server is burning 80% of the context"

**Audience:** MCP authors on X, the MCP Discord, the Anthropic Discord.
This is the "how is this different from raw MCP?" demo.
**Hook:** "Same Postgres. Same question. Two MCP servers. One burns
8,000 tokens, the other burns 200."
**Format:** 60s side-by-side video.

### Script
| t | Left pane: raw MCP server | Right pane: Elliot connector |
|---|---|---|
| 0:00 | "Both servers expose one tool: query_films." | (titles fade in) |
| 0:10 | Agent asks "highest grossing comedies" | (same) |
| 0:15 | Tool returns 6,400 rows. Agent's context: ⚠ | Tool applies category filter + cap. 5 rows. |
| 0:25 | Studio: "8,213 tokens — 73% of your budget" | Studio: "247 tokens — green" |
| 0:35 | "And the agent has to summarize all of that, costing another roundtrip." | "Agent answers directly." |
| 0:50 | "Elliot's lint would have caught this before you deployed." | `elliot lint demo.connector.json` → red error |
| 1:00 | "Token budgeting is a first-class lint principle, not an afterthought." | (end card: docs/five-principles) |

### Recording commands
```bash
# Generate the bad MCP server (10 lines, no filter, no cap)
cat > /tmp/bad-mcp.py <<'PY'
from mcp.server.fastmcp import FastMCP
import psycopg
mcp = FastMCP("bad")
@mcp.tool()
def query_films(q: str) -> list[dict]:
    conn = psycopg.connect("…")
    return [dict(r) for r in conn.execute(q)]
PY

# Elliot side: a 30-line connector.json with filters + size cap
elliot init --template postgres-readonly demo.connector.json
elliot lint demo.connector.json    # green
```

---

## Demo 3 — "Agent gets a 500, recovers, retries"

**Audience:** dev-tools VCs and AI engineers on X, in DMs, on calls.
The "actionable errors" principle made visible.
**Hook:** "Most MCP servers tell the agent 'something went wrong.' Elliot
tells it exactly what to do next."
**Format:** 45s screen-record of the Agent Console replay.

### Script
| t | Voice over | Console |
|---|---|---|
| 0:00 | "Real connector. The upstream API is rate-limited at 60/min." | trace starts |
| 0:08 | "First call: success." | green tool_call row |
| 0:15 | "Second call hits the rate limit. A normal MCP server returns 'error: 429.'" | red row appears |
| 0:22 | "Elliot returns this." | inline JSON: `{"code":"RATE_LIMITED","retry_after_seconds":12,"message":"Wait 12s, then retry the same call."}` |
| 0:30 | "Agent reads the structured shape, waits, retries. Trace shows the recovery." | next row: 12s gap → success |
| 0:40 | "Five principles, one of which is 'errors are actionable.' This is what that means in production." | (end card) |

### Recording commands
```bash
# Use the rate-limited example connector (templates/rate-limited.connector.json)
elliot init --template rate-limited /tmp/rl.connector.json
# Drive the agent to overrun the limit in a controlled way
```

---

## Demo 4 — "One connector, four agents"

**Audience:** "which coding agent should I use?" crowd — Cursor / Claude
Code / Codex / OpenClaw users in their respective subreddits and Discords.
**Hook:** "Write the connector once. Use it in every coding agent you have."
**Format:** 60s asciinema, four panes.

### Script
| t | What's on screen |
|---|---|
| 0:00 | Four tmux panes: Claude Code, Cursor, Codex, OpenClaw |
| 0:05 | `elliot connect` writes the MCP config for each detected client |
| 0:15 | Same prompt typed into all four: "list films released in 2006 with rentals > 30" |
| 0:25 | All four panes: tool call → result → answer |
| 0:40 | Studio Metrics page → harness breakdown shows all four clients side by side |
| 0:55 | "One connector. Four runtimes. One trace store." (end card) |

### Recording commands
```bash
make dev                       # starts plugin + studio + writes MCP configs
# in each terminal pane:
claude        # or: cursor . / codex / openclaw
```

---

## Demo 5 — "Publish a connector and share the URL" (Elliot Cloud)

**Audience:** team leads and indie builders who would rather not run Docker.
**Hook:** "I built a connector for our internal API in 8 minutes. Here's the
URL — any teammate can wire their Claude Code to it now."
**Format:** 75s screen-record (browser → terminal).

### Script
| t | Voice over | Visual |
|---|---|---|
| 0:00 | "Elliot Cloud, fresh org." | dashboard |
| 0:10 | "Define a source — our staging Postgres URL — and store the password as a tenant secret." | Sources → Secrets |
| 0:30 | "Define one tool: list_open_tickets." | Tools → editor |
| 0:45 | "Lint. Publish. Done." | green checks → `Publish` button |
| 0:55 | "I get a stable MCP URL." | `https://cloud.elliot.dev/t/acme/c/support/mcp/` |
| 1:05 | "Paste it into Claude Code. The tool is there." | terminal: `claude` → tool list shows |
| 1:15 | "Every agent call shows up in Observability — per tenant, per connector." | Observability page |

### Recording commands
```bash
# render or fly deploy; or local docker-compose for the recording
cd Elliot-cloud- && docker compose up --build
open http://localhost:5173
```

---

## Production checklist before recording

For all five:

1. Run through the demo end-to-end once. Time it. Cut anything past 90s.
2. Studio at 100% zoom, dark mode, font ≥ 16px (the README font isn't readable
   in a 720p Twitter clip otherwise).
3. Terminal in a 100×30 window with `PS1='$ '` — no full-path prompts.
4. asciinema, not video, for any pure-terminal demo. Smaller, hostable on
   the docs site, and copy-pasteable.
5. End card: `github.com/EliBarak12/Elliot` and one specific verb ("docker
   one-liner in README"). No "follow me" pleas.
6. Caption every clip. Most viewers watch muted. Subtitle the voice-over.
7. Upload originals to the repo at `docs/screenshots/` so future contributors
   can re-cut them.

## Distribution alignment

Demo 1 → Show HN, README hero GIF, Twitter pinned post.
Demo 2 → MCP author Twitter circle, MCP Discord, "show your work" threads.
Demo 3 → VC DMs, AI engineer newsletter pitches, Cursor Discord.
Demo 4 → r/cursor, r/ClaudeAI, r/LocalLLaMA, OpenClaw Discord.
Demo 5 → Indie hacker / build-in-public audience on X, Render template gallery.

See `docs/DISTRIBUTION.md` for which person on which platform actually
clicks on which demo.
