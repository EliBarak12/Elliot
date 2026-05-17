# Agent Experience (AX) at Elliot

The broader industry is converging on a set of **Agent Experience principles** for designing digital services that agents — not just humans — can use as a first-class medium. Elliot's [five principles](/docs/five-principles) are about how to design *individual tools*. This page maps the wider AX principles onto what Elliot actually does, where it falls short today, and what's on the roadmap.

If you only remember one thing: **the agent is the user now**, and you can't ship a great agent experience without measuring it. Elliot is the platform that lets you do both.

## Why AX matters

Agents are a delegated medium for end users. The end user never disappears — they just stop driving the keyboard. That has two consequences:

1. **Parity** — anything a user can do in your browser app, your delegated agent should be able to do, too. Where you force a human-in-the-loop, you cap the quality ceiling of every agent experience built on top of you.
2. **Observability** — because the agent is non-deterministic, the only way to know whether your service is actually serving end users is to measure how agents use it. This is what you instrument when you adopt AX.

## Service-side principles → Elliot

### 1. Human Centricity

Agents are delegates of humans. Designing for them is anchored on designing for human needs.

- **What Elliot does:** the entire builder loop — `discover-source` → `build-connector` → `lint-connector` → `run-eval` → `deploy-connector` — is exposed as MCP tools so a product engineer (the human) keeps full design authority. The agent assists; it doesn't decide. Studio is the human's view into what agents are doing on their users' behalf.
- **Where we're going:** richer human-in-the-loop hooks for connector approval flows so a human signs off before a connector goes live.

### 2. Agent Accessibility

Reduce forced human interaction; aim for parity between agent and browser/app interfaces.

- **What Elliot does:** every connector ships through MCP, so any compliant client (Claude Code, Cursor, OpenClaw, Codex, …) gets identical access. Cross-source JOINs in `core/sql.py` mean an agent doesn't pay the cost of three round-trips to do what a SQL view would do for a human dashboard.
- **Where we're going:** structured authorization scopes per tool so the rare flows that must involve a human (payments, credential changes) can prompt for explicit consent without ejecting the agent from the session.

### 3. Contextual Alignment

Provide agents with the context they need to use the system correctly across models.

- **What Elliot does:**
  - The `prompts/get name=getting_started` MCP prompt teaches every connecting agent the five tool-design principles on first connect, regardless of model.
  - Errors carry a structured `{code, message, details}` shape (see `packages/core/src/elliot_core/errors.py`) so agents recover instead of guessing.
  - Each result is annotated with a token estimate — the agent can budget its context window before it overruns.
  - `connector://schema` and `connector://sample/<tool_id>` MCP resources let an agent fetch design context **out-of-band** instead of burning context on a `tools/list` round-trip.
- **Where we're going:** doc-consistency tooling so the linter checks that every public tool description matches what's served at `connector://schema`.

### 4. Agent Interactivity Patterns

Standardised patterns for sensitive flows — purchases, auth, destructive actions.

- **What Elliot does:** every tool carries an MCP `destructiveHint` annotation derived from its declared category (`READ` / `WRITE` / `ACTION`, see `packages/core/src/elliot_core/connector/schema_gen.py`). When the operator sets `ELLIOT_REQUIRE_DESTRUCTIVE_CONFIRMATION=true`, every `WRITE` / `ACTION` tool gains a required `confirm: bool` parameter and returns a structured `CONFIRMATION_REQUIRED` error if the agent tries to invoke it without an explicit confirmation. The error is actionable — the agent knows exactly how to recover (re-call with `confirm=true` after authorising the operation with the user).
- **Where we're going:** declarative per-tool confirmation policy in `connector.json` so a connector author can mandate confirmation on a single mutation without globally enabling the gate.

### 5. Differentiate Agent Interaction

Capture the fact that a request came from an agent — and *which* agent — in metrics, logs, traces, and audit logs.

- **What Elliot does:** every request to the runtime is parsed for the AX `User-Agent` convention (`agent-<tool>[/<version>] [model-<id>] [modality-<m>]`) and a handful of common MCP client UA strings. The parsed `AgentIdentity` (client, version, model, modality, raw UA) is bound to a contextvar for the request lifetime, written to the session NDJSON, and stored on the `agent_sessions` table alongside the legacy `agent_hint` column. Studio's Agent Console renders the structured client and model as badges so you can see, at a glance, which model uses which tool best — and which one fails most.

  Implementation: `packages/core/src/elliot_core/agent_identity.py`, `packages/core/src/elliot_core/http_middleware.py:AgentIdentityMiddleware`, `packages/connector-runtime/src/elliot_connector_runtime/observation_store.py`.
- **Where we're going:** per-session aggregates in Studio (calls, error rate, token cost) **broken down by client and model** so connector authors can spot model-specific regressions.

## Agent-side principles → what we ask of agent clients

### Mindful Digital Collaboration

Respect the boundaries the connector sets. Elliot enforces parameterised SQL, sandboxes file reads to allowed roots, masks secrets in audit output, and rate-limits per IP. Misbehaving agents get blocked by the runtime, not silently tolerated.

### Adopt Optimal Practices

When you build an agent that talks to Elliot, please:

- Send an AX-format `User-Agent` so observability can attribute calls.
- Read `connector://schema` and `connector://sample/<tool_id>` resources before guessing parameter shapes — they're free of tool-list token budget.
- Prefer the structured `getting_started` prompt over heuristics for first-call learning.

### Transparent Identity

The minimum we ask:

```
User-Agent: agent-<your-tool>/<version> <model-id> [modality-<m>]
```

Examples:

```
User-Agent: agent-claude-code/1.42.0 claude-opus-4-7 modality-plaintext
User-Agent: agent-cursor/0.45 model-claude-sonnet-4-5
User-Agent: agent-codex
```

If your client can't customise the `User-Agent`, set the `x-client-name` header instead.

### Provide Feedback

Elliot already publishes per-call telemetry (token estimate, latency, row count, error code) to the connector author through Studio. Agent vendors who want to consume this signal — to detect a tool whose description is misleading their model, for example — can scrape `/v1/metrics/token-efficiency` or `/v1/sessions`. We're tracking an OpenTelemetry export profile so this becomes pull-based at scale.

## Read more

- [The five principles](/docs/five-principles) — Elliot's tool-level design rules
- [Concepts](/docs/concepts) — connectors, sources, tools, sessions
- [Architecture](/docs/architecture) — how the plugin, runtime, and Studio fit together
