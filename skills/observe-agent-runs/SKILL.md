---
name: observe-agent-runs
description: Wire the Elliot trace hook into a coding agent (Claude Code, Codex, Cursor) so its prompts, model reasoning, tool calls, and final answers stream live into the Elliot Agent Console alongside the MCP tool calls.
when_to_use: Trigger when the user says "I want to see what my agent is doing", "stream my agent runs into Elliot", "install the trace hook", "show prompts and reasoning in the Console", "turn on observability", or when MCP tool calls are visible in Studio but the surrounding context (prompt, reasoning, final answer) is not.
argument-hint: "[harness]"
allowed-tools: Bash mcp__elliot__*
---

# Observe Agent Runs

You are wiring the Elliot trace hook into a coding agent's config so the full
session — prompt, model reasoning, tool calls, and final answer — appears in
the Agent Console. Without the hook the Console only sees MCP tool calls,
which is half the story: the *why* lives in the prompt and the reasoning.

This is principle #4 — **every agent session is observable** — operationalised.

## Prerequisite

Elliot must be running (`make dev`). The hook posts to the connector-runtime
at `http://localhost:3001/v1/trace/ingest`, so the runtime port (`3001`) needs
to be reachable from the agent's machine. If the user runs Elliot on a remote
host, set `ELLIOT_RUNTIME_URL` in their shell before installing.

## Steps

### 1. Check current state

Call `elliot_trace_hook_status`. It returns the runtime URL the hook will
post to and, for each supported harness (`claude-code`, `codex`, `cursor`),
whether it's installed today and the config path it lives in.

If the harness the user uses already shows `installed: true`, jump to step 3
and tell them what they'd see when they next run that harness.

### 2. Install for the right harness

Ask the user which agent they want streamed into Elliot (or detect from
context — if they're talking to you in Claude Code, default to `claude-code`).

Call `elliot_install_trace_hook(harness="<harness>")` with one of:
`claude-code`, `codex`, `cursor`.

It writes a hook entry into the harness config (e.g.
`~/.claude/settings.json` for Claude Code), returns the config path it
touched, and the runtime URL the hook will post to. Tell the user:

> "Installed the trace hook into `<config_path>`. Restart `<harness>`; its
> next prompts, reasoning, tool calls, and final answers will stream into
> the Agent Console at http://localhost:5173/agents."

### 3. Verify it works

After the user restarts the harness and makes one call, ask them to refresh
the Agent Console. They should see a new run entry that includes the prompt
text and the model's reasoning, not just the tool calls.

If nothing appears:
- Confirm the runtime is healthy with `elliot_runtime_logs` and a check of
  `:3001/health`.
- Confirm the hook is still installed with `elliot_trace_hook_status`.
- If `ELLIOT_RUNTIME_URL` is set to a non-default value, confirm the harness
  process actually inherits that env var.

### 4. Uninstall when done

If the user wants to stop streaming runs (e.g. before sharing the harness
config with a teammate), call
`elliot_uninstall_trace_hook(harness="<harness>")`. It removes the hook
entry from the same config file, leaving everything else intact.

## Rules

- Only install the hook the user actually asks for. Don't install all three
  harnesses by default — each one writes into a config file the user owns.
- Never log the runtime URL with credentials attached. The runtime endpoint
  is unauthenticated locally; if the user has put it behind a proxy with a
  token, that token lives in the proxy config, not in the hook.
- The hook ships prompts and reasoning. If the user works on sensitive
  material, warn them once before installing.
