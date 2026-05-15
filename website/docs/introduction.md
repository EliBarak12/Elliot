# Introduction

> **AX** is to AI agents what UX is to users and DX is to developers. Elliot is the interface layer that makes your existing product feel native to agents.

Connecting an API to Claude is easy. Making it work *well* with agents is the hard part. Agents fail when:

- Tool descriptions are vague → the wrong tool gets called
- Results are too large → the context window fills up
- Errors are unstructured → the agent can't recover
- There is no observability → you don't know it's broken

Elliot makes these problems visible and fixable. You describe your data sources and the tools you want exposed in a single `.connector.json` file. Elliot does schema generation, HTTP fetching, safe parameterised SQL, auth, audit logging, and MCP registration.

## What you get

| Piece | What it does |
|---|---|
| `elliot-core` | Types, query builder, linter, eval harness |
| `elliot-mcp-plugin` | FastMCP server on `:3000` — agents connect here |
| `elliot-connector-runtime` | Tool execution + session tracking on `:3001` |
| `elliot-studio` | React 19 dashboard on `:5173` — observe, run, edit |

## Who it's for

A **product engineer** who already has a working API or database and wants AI agents to interact with it natively — with minimum tokens, clean error recovery, and full observability of every session.

If that's you, the [quickstart](./quickstart) takes about five minutes.

## The promise

Elliot is built around five non-negotiable principles. They are the difference between a tool an agent occasionally gets right and a tool it can call reliably in production. Read them in full → [The five principles](./five-principles).
