---
layout: home
title: Elliot — Make your product agent-ready
titleTemplate: false

hero:
  name: Elliot
  text: Build your connector. Make your product agent-ready.
  tagline: Elliot turns any API or database into a connector your AI agents can call natively — with minimum tokens, clean error recovery, and full session observability. One file, one command, every agent.
  image:
    src: /hero-glow.svg
    alt: Elliot
  actions:
    - theme: brand
      text: Build a connector
      link: /docs/quickstart
    - theme: alt
      text: Read the docs
      link: /docs/introduction
    - theme: alt
      text: View on GitHub
      link: https://github.com/EliBarak12/Elliot

features:
  - icon:
      src: /icons/agent-ready.svg
      width: 30
      height: 30
    title: Agent-ready, by design
    details: Every connector is linted against the five AX principles before it ships — verb-first descriptions, typed parameters, context-sized results.
  - icon:
      src: /icons/safe.svg
      width: 30
      height: 30
    title: Safe by default
    details: Parameterised SQL, read-only database transactions, env-var secrets. Connector files contain no keys and are safe to commit.
  - icon:
      src: /icons/observable.svg
      width: 30
      height: 30
    title: Every call observable
    details: Tokens, latency, args, errors — every agent call streamed to an NDJSON audit log and visible in Studio.
  - icon:
      src: /icons/one-command.svg
      width: 30
      height: 30
    title: One command to run
    details: One Docker command brings up the plugin, runtime, and Studio together — no Python, Node, or toolchain to install.
  - icon:
      src: /icons/every-agent.svg
      width: 30
      height: 30
    title: Works with every agent
    details: Claude Code, Cursor, OpenClaw, Codex — Elliot auto-registers your connector with each one.
  - icon:
      src: /icons/agentic.svg
      width: 30
      height: 30
    title: Agents build connectors
    details: discover-source → build → lint → eval → deploy. The platform itself is agentic — agents build connectors through Elliot.
---

