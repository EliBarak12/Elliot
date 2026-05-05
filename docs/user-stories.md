# Elliot — User Stories & Personas

## The Real User

**A product engineer who already has a working API or database and wants to make it genuinely usable by AI agents — not just callable, but designed so agents understand it, use it efficiently, and get good answers.**

---

## Persona 1 — Alex, Backend Engineer

> "I have a REST API. I want Claude Code to query it without me writing a wrapper every time. But I also want to know if Claude is using it correctly."

## Persona 2 — Maria, Solo Founder

> "I have a PostgreSQL database with all my business data. I want Claude to help me run my company — answer questions, spot patterns, flag anomalies — without me switching between apps."

## Persona 3 — Team Lead, Mid-size Company

> "I want any agent — Claude Code, Copilot, whatever the team uses — to be able to use our internal API as a first-class data source. And I want to know if the tools are actually good enough."

---

## What 'Good Enough' Looks Like

| Signal | Good | Needs work |
|---|---|---|
| Linter | 0 errors, 0 warnings | Any ERROR or WARNING |
| Eval pass rate | 100% | < 100% |
| Avg tokens per call | < 300 | > 500 |
| Error rate (Agent Console) | < 2% | > 5% |
| Token cost per session | < 1,000 | > 3,000 |
| Tool call retries (same tool, same session) | 0 | ≥ 1 (agent confused) |
