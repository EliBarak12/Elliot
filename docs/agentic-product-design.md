# Elliot — Agentic Product Design

## The Real Problem

Most products were built for humans. Humans navigate UIs, read documentation, and recover from ambiguous errors by trying something else. **AI agents are not humans.** They make decisions based on tool descriptions, they can't retry without guidance, they have limited context windows, and they fail silently when tools are poorly designed.

The question Elliot answers is not *"can Claude call my API?"* It is:

> **"Is my product genuinely agent-ready — and how do I know?"**

---

## What a Connector Is

A **Connector** represents a **business domain** — not a single API or database.

One connector can span any number of underlying data sources: REST APIs, PostgreSQL tables, MySQL tables, CSV files, JSON files. All data is ingested into an in-memory SQLite database so tools can JOIN across sources in a single query.

---

## The Five Principles of Agent-Ready Tools

### 1. Descriptions are contracts, not labels

| Bad | Good |
|---|---|
| `"Get data"` | `"Return all animals, optionally filtered by species and status"` |
| `"User info"` | `"Get a single user by their integer ID. Returns 404 error if not found."` |
| `"Run query"` | `"Count orders placed in the last N days, grouped by status"` |

**Rule**: Start with a verb. State what the tool returns. State key parameters. State what errors are possible.

### 2. Parameters are typed and named for agents, not humans

### 3. Results are sized for context windows

### 4. Errors tell agents what to do next

### 5. Tool sets are minimal and orthogonal
