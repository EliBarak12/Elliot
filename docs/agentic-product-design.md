# Elliot — Agentic Product Design

## The Real Problem

Most products were built for humans. Humans navigate UIs, read documentation, and recover from ambiguous errors by trying something else. **AI agents are not humans.** They make decisions based on tool descriptions, they can’t retry without guidance, they have limited context windows, and they fail silently when tools are poorly designed.

The question Elliot answers is not *“can Claude call my API?”* It is:

> **“Is my product genuinely agent-ready — and how do I know?”**

---

## What “Agentic Native” Means

A product is **agentic native** when:

1. **Agents discover the right tool automatically** — because tool descriptions are precise, verb-first, and unambiguous
2. **Agents call tools correctly on the first try** — because parameters are named clearly and types are explicit
3. **Agents recover cleanly from errors** — because errors are structured, actionable, and tell the agent what to do next
4. **Results fit in the agent’s context window** — because tools return the minimum data needed, not full table dumps
5. **No token waste** — because result shapes are compact and consistent

If any of these five conditions fails, agents either hallucinate, retry in circles, or give up.

---

## The Feedback Loop Elliot Provides

```
  ┌──────────────────────────────────────────┐
  │          Design your tools                  │
  │   (connector.json + quality linter)         │
  └─────────────────┬───────────────────────┘
                   ↓
  ┌──────────────────────────────────────────┐
  │         Validate with eval cases             │
  │   (eval.yaml → run → pass/fail report)      │
  └─────────────────┬───────────────────────┘
                   ↓
  ┌──────────────────────────────────────────┐
  │        Deploy to real agents                 │
  │   (Claude Code / Codex / any MCP client)    │
  └─────────────────┬───────────────────────┘
                   ↓
  ┌──────────────────────────────────────────┐
  │        Observe real agent sessions           │
  │   (Studio Agent Console → full trace)       │
  └─────────────────┬───────────────────────┘
                   ↓
  ┌──────────────────────────────────────────┐
  │        Improve based on data                 │
  │   (token cost, error rate, retry rate)      │
  └──────────────────────────────────────────┘
                   ↓
               (back to top)
```

---

## The Five Principles of Agent-Ready Tools

### 1. Descriptions are contracts, not labels

An agent reads the tool description to decide whether to call it. A bad description causes the agent to call the wrong tool, call no tool, or hallucinate.

| Bad | Good |
|---|---|
| `"Get data"` | `"Return all animals, optionally filtered by species and status"` |
| `"User info"` | `"Get a single user by their integer ID. Returns 404 error if not found."` |
| `"Run query"` | `"Count orders placed in the last N days, grouped by status"` |

**Rule**: Start with a verb. State what the tool returns. State key parameters. State what errors are possible.

### 2. Parameters are typed and named for agents, not humans

Agents fill in parameter values based on name, type, and description. A parameter named `q` is ambiguous. A parameter named `status_filter` with description `"One of: open, closed, pending"` is not.

| Bad | Good |
|---|---|
| `q: string` | `search_query: string — "keyword to match against animal name"` |
| `n: integer` | `limit: integer — "max rows to return, default 20"` |
| `f: boolean` | `include_archived: boolean — "if true, include soft-deleted records"` |

### 3. Results are sized for context windows

A tool that returns 5,000 rows of raw JSON will fill the agent’s context window. The agent can’t reason about it and will produce a bad answer. Every tool should return the minimum data needed to answer the question.

| Problem | Solution |
|---|---|
| `SELECT *` on a large table | Add a `LIMIT 50` default in the SQL |
| Returning all fields | `SELECT id, name, status` — only the fields the agent needs |
| Nested JSON with deep structure | Use `data_path` to extract just the list; use `json_flattener` to flatten |
| No pagination | Add `offset: integer` parameter for large collections |

**Token budget**: Aim for < 500 tokens per tool result. Flag any result over 2,000 tokens as a risk.

### 4. Errors tell agents what to do next

When a tool call fails, the agent reads the error message and decides whether to retry, try a different tool, or give up. A generic `500 Internal Server Error` gives the agent nothing to work with. A structured error with a code and a message does.

```json
// Bad: agent gives up
{ "error": "Something went wrong" }

// Good: agent knows to retry with a different value
{
  "error": {
    "code": "VALIDATION_INVALID_SPECIES",
    "message": "species must be one of: dog, cat, bird, fish",
    "details": { "valid_values": ["dog", "cat", "bird", "fish"] }
  }
}
```

### 5. Tool sets are minimal and orthogonal

Every tool you add is a decision the agent has to make. More tools = more tokens spent on tool selection = higher chance of choosing the wrong one.

**Rule**: If two tools can be merged with an optional parameter, merge them. If a tool is rarely used, remove it. Start with 3–5 tools and add more only when real agent sessions show they’re needed.

---

## What Elliot Adds to the Architecture

### Currently built (tasks 001–059)
- Connector definition format + validator
- MCP plugin server (tool discovery + execution)
- Connector runtime (fetch + SQL + audit log)
- Studio UI (manual testing, basic audit view)
- Structured logging + error middleware

### Missing — the observability and quality layer (tasks 060–065)

| Component | What it does | Where |
|---|---|---|
| **Agent Session Tracker** | Groups all MCP events from one agent connection into a structured session | `connector-runtime/session_tracker.py` |
| **Tool Quality Linter** | Static analysis of connector definitions: description length, unbounded SELECTs, parameter clarity, token risk | `core/linter.py` |
| **Eval Test Case Format** | YAML format to define “given this tool call with these args, expect these results” | `*.eval.yaml` per connector |
| **Eval Runner** | CLI that runs eval cases against the live runtime, produces pass/fail/score report | `core/eval_runner.py` |
| **Studio Agent Console** | Real-time session viewer: every agent connection, every tool call, params, result size, token estimate, errors | `studio/pages/AgentConsole.tsx` |
| **Token Efficiency Metrics** | Per-tool average token cost, largest results, LIMIT suggestions | `studio/pages/Metrics.tsx` (extended) |

---

## Agent Session: What It Looks Like

Instead of logging individual tool calls, Elliot tracks the full agent session:

```json
{
  "session_id": "a3f9b1c2",
  "started_at": 1746267000.0,
  "agent_hint": "claude-code/1.2.0",
  "events": [
    {
      "ts": 1746267000.1,
      "type": "tools_list",
      "tool_count": 5,
      "duration_ms": 12.3
    },
    {
      "ts": 1746267001.5,
      "type": "tool_call",
      "tool_id": "list_animals",
      "arguments": { "species": "dog" },
      "result_rows": 3,
      "result_token_estimate": 87,
      "duration_ms": 43.2,
      "error": null
    },
    {
      "ts": 1746267002.8,
      "type": "tool_call",
      "tool_id": "get_animal",
      "arguments": { "id": 1 },
      "result_rows": 1,
      "result_token_estimate": 31,
      "duration_ms": 21.0,
      "error": null
    }
  ],
  "total_tool_calls": 2,
  "total_tokens_estimated": 118,
  "total_duration_ms": 64.2,
  "error_count": 0
}
```

---

## Tool Quality Linter: Example Output

```
$ elliot lint my-api.connector.json

Connector: Pet Store API (petstore v1.0.0)

ERROR   list_all   UNBOUNDED_SELECT: "SELECT * FROM animals" — no LIMIT clause.
                   Agents may receive thousands of rows, filling their context window.
                   Fix: add WHERE or LIMIT, or add a `limit` parameter.

WARN    get_by_id  DESCRIPTION_MISSING_VERB: description starts with "Animal by"
                   Fix: rewrite as "Get a single animal by its integer ID"

WARN    search     PARAMETER_NAME_UNCLEAR: parameter name "q" is ambiguous.
                   Fix: rename to "search_query" with a description.

INFO    create     WRITE_TOOL: this tool modifies data. Ensure your description
                   says "Creates a new..." so agents don’t call it accidentally.

3 issues (1 error, 2 warnings, 1 info)
```

---

## Eval Test Cases: Example

```yaml
# pets.eval.yaml
name: Pet Store Eval Suite
connector: petstore

cases:
  - id: list_all_animals
    description: "Agent should be able to list all animals with no filters"
    tool_id: list_animals
    arguments: {}
    expect:
      min_rows: 1
      fields_present: ["id", "name", "species"]
      max_token_estimate: 500

  - id: filter_by_species
    description: "Agent should be able to filter animals by species"
    tool_id: list_animals
    arguments:
      species: "dog"
    expect:
      min_rows: 0
      all_rows_match:
        field: species
        value: dog

  - id: get_nonexistent_animal
    description: "Agent should get a structured error for missing IDs"
    tool_id: get_animal
    arguments:
      id: 999999
    expect:
      error_code: NOT_FOUND
```

Run:

```bash
uv run elliot eval pets.eval.yaml

PASS  list_all_animals      5 rows, 87 tokens, 43ms
PASS  filter_by_species     2 rows, all species=dog, 38ms
PASS  get_nonexistent_animal  error NOT_FOUND as expected

3/3 passed
```

---

## Studio Agent Console: What the Developer Sees

```
Agent Console                                    ● Live (last 60s)
───────────────────────────────────────────────────────────────────
▼ a3f9b1c2  claude-code  14:32:01  2 calls  118 tokens  64ms  ✓
   └ tools/list               5 tools discovered          12ms
   └ list_animals {species:dog}  3 rows  87 tokens         43ms  ✓
   └ get_animal {id:1}          1 row   31 tokens          21ms  ✓

► f7a2e001  claude-code  14:28:44  4 calls  1,823 tokens  210ms  ⚠ large result

► 9c3b0d12  claude-code  14:15:02  1 call   0 tokens      12ms   ✗ error
───────────────────────────────────────────────────────────────────
  Session f7a2e001 used 1,823 tokens — list_all returned 94 rows.
  Suggestion: add LIMIT 50 to the list_animals SQL query.
```

This is the core feedback loop: the developer sees exactly how agents interact with their tools, and Elliot tells them what to fix.
