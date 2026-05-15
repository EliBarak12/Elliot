---
layout: home
title: Elliot — AX Platform for AI Agents
titleTemplate: false

hero:
  name: Elliot
  text: AX is the new UX.
  tagline: Turn any API or database into agent-native MCP tools. Design, validate, deploy, and observe agent-ready tools with minimum tokens, clean error recovery, and full session observability.
  image:
    src: /hero-glow.svg
    alt: Elliot
  actions:
    - theme: brand
      text: Get started
      link: /docs/quickstart
    - theme: alt
      text: Read the docs
      link: /docs/introduction
    - theme: alt
      text: View on GitHub
      link: https://github.com/EliBarak12/Elliot

features:
  - icon: 🧭
    title: Agent-readiness, by design
    details: Every tool description, parameter, and return shape is linted against the five AX principles before it ships.
  - icon: 🛡️
    title: Safe by default
    details: Parameterised SQL, env-var secrets, RBAC-ready auth. Connector files are safe to commit.
  - icon: 🔭
    title: Full session observability
    details: Tokens, latency, args, errors — every agent call streamed to an NDJSON audit log and visible in Studio.
  - icon: ⚙️
    title: One command to run
    details: make dev brings up the plugin (:3000), runtime (:3001), and Studio (:5173). Honcho-powered.
  - icon: 🧩
    title: Any MCP client
    details: Claude Code, Cursor, Codex, Windsurf, VS Code Copilot — Elliot auto-registers itself with every detected agent.
  - icon: 🤖
    title: Agents build connectors
    details: discover-source → build → lint → eval → deploy are themselves MCP tools. The platform is agentic.
---
