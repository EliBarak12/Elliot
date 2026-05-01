# Elliot — Core Concepts

This document explains the fundamental domain model of the Elliot platform. Understanding these concepts is essential for building and using the system correctly.

---

## 1. Product

A **Product** is the user's existing software system — the thing they already built. It has:

- A **base URL** (e.g., `https://api.myapp.com`)
- An **authentication method** (API key, OAuth2, Basic Auth, or none)
- A set of **endpoints** (the operations it can perform)
- Optionally a **database** or other data sources

In Elliot, you register your product once and then build everything else on top of it. The product's credentials are stored encrypted and are never exposed to AI agents — Elliot injects them transparently at runtime when making calls on behalf of agents.

**Examples of Products:**
- A CRM system with APIs to list contacts, create deals, send emails
- An e-commerce backend with APIs to query orders, update inventory, process refunds
- An internal analytics system with a database and REST endpoints
- Any SaaS with a documented API

---

## 2. Endpoint

An **Endpoint** is a single operation your Product exposes — one HTTP route. Endpoints are imported from your product (via OpenAPI spec, Postman collection, or manual entry) and stored in Elliot as structured metadata.

Each endpoint has:
- `method`: GET / POST / PUT / DELETE / PATCH
- `path`: e.g., `/v1/customers/{id}`
- `parameters`: path params, query params, request body schema
- `response_schema`: what the endpoint returns
- `description`: human-readable summary (used by AI tools)

Endpoints are the raw material. Tools and Skills are built on top of them.

---

## 3. Tool

A **Tool** is an AI-callable atomic operation. It maps one (or occasionally multiple) Endpoint(s) into a well-described, parameter-typed interface that AI agents can discover and invoke.

### What makes a good Tool

A good Tool has:
- A **clear name** (snake_case, verb-first): `get_customer_by_id`, `create_invoice`, `list_open_orders`
- A **precise description**: The AI reads this to decide when and how to use the tool
- **Typed parameters** with descriptions: The AI uses these to fill in values
- A **response mapping**: Which fields to return (avoids dumping irrelevant data to the agent)
- A **category**: READ (safe, idempotent) or ACTION (has side effects)

### Tool categories

| Category | When to use | Examples |
|---|---|---|
| `READ` | Fetching or querying data (safe to retry) | `get_order`, `list_customers`, `search_products` |
| `ACTION` | Creating, updating, deleting, or triggering something | `create_ticket`, `send_email`, `update_status` |
| `MIXED` | Upsert-style operations (create or update) | `sync_contact`, `upsert_record` |

### Parameter mapping

Tools have two kinds of parameters:
- **Forced values**: Always sent with a fixed value (e.g., `status=active` always)
- **Agent-provided values**: The AI fills these in at runtime based on context

### How Tools differ from raw API calls

| Raw API Call | Elliot Tool |
|---|---|
| Technical HTTP contract | Natural language interface |
| Requires knowing path, method, auth | Agent just knows name + description |
| Returns full response payload | Returns mapped, relevant subset |
| No context for AI | Rich description guides AI decision-making |

---

## 4. Skill

A **Skill** is a multi-step, composed workflow that chains multiple Tools together to accomplish a higher-level goal. Skills represent capabilities that require more than one operation.

### Why Skills exist

Most real-world tasks require multiple API calls. Without Skills, an AI agent would need to figure out the sequence itself (which is unreliable and slow). Skills encode that knowledge explicitly.

**Example — "Onboard a new customer" Skill:**
1. Call `create_customer` (ACTION tool) → returns `customer_id`
2. Call `create_default_subscription` with the `customer_id` (ACTION tool)
3. Call `send_welcome_email` with `customer_id` (ACTION tool)
4. Call `log_onboarding_event` with `customer_id` (ACTION tool)

Without a Skill, an agent would have to infer all four steps. With a Skill, it's one call.

### Orchestration modes

| Mode | How it works | Best for |
|---|---|---|
| `sequential` | Steps run in fixed order; output of step N feeds into step N+1 | Predictable, linear workflows |
| `conditional` | Steps have if/else branching based on tool outputs | Workflows with different paths |
| `ai_orchestrated` | Elliot's runtime LLM decides step order at runtime based on the goal and available tools | Complex, open-ended workflows |

### Data passing between steps

In `sequential` mode, steps are connected with **data bindings**:
```json
{
  "steps": [
    {
      "tool": "create_customer",
      "input": { "name": "{{skill.input.customer_name}}", "email": "{{skill.input.email}}" },
      "output_alias": "customer"
    },
    {
      "tool": "send_welcome_email",
      "input": { "customer_id": "{{steps.customer.id}}", "name": "{{skill.input.customer_name}}" }
    }
  ]
}
```

`{{skill.input.X}}` — value from the skill's input parameters
`{{steps.ALIAS.FIELD}}` — value from a previous step's output

---

## 5. Prompt

A **Prompt** is a piece of AI instruction associated with your Connector. Prompts tell the agent how to behave when using your product's tools and skills.

### Prompt types

| Type | Purpose | Example |
|---|---|---|
| `system` | Sets overall agent behavior and product context | "You are a customer support assistant for Acme Corp. You have access to the customer database and support ticket system. Always be professional..." |
| `template` | Reusable prompt with variable substitution | "Summarize the account status for customer {{customer_name}} including their {{subscription_tier}} plan and last {{N}} orders." |
| `few_shot` | Sample conversations that demonstrate correct agent behavior | Q: "What did customer X order last week?" A: [tool_call: list_orders, filter: last_7_days] |

### Why Prompts matter

The same set of Tools can produce very different agent behavior depending on how the system prompt is written. A well-crafted system prompt:
- Defines the agent's persona and role
- Sets boundaries (what the agent should and shouldn't do)
- Explains domain-specific context the AI doesn't know otherwise
- Reduces hallucination by grounding the agent in product reality

---

## 6. Connector

A **Connector** is the packaged, deployable artifact that combines your Tools, Skills, and Prompts into a live AI interface for your product.

### What a Connector exposes

```
https://runtime.elliot.ai/c/{your-connector-slug}
```

This single URL is an MCP-compatible endpoint that:
- Returns a tool manifest (all your tools + skills)
- Accepts tool invocation requests
- Executes the underlying API calls against your product
- Returns structured results to the agent

### Connector versioning

Connectors are versioned (semantic versioning). You can:
- Deploy a new version without breaking existing agent integrations
- Roll back to a previous version
- Run multiple versions simultaneously (e.g., v1 for legacy clients, v2 for new ones)

### Access control

| Access type | Who can use it |
|---|---|
| `api_key` | Anyone with a valid API key you generated |
| `public` | Anyone with the URL (no auth) |
| `oauth` | Users who authenticate via OAuth2 flow (future) |

### Protocol support

| Protocol | Status | Use case |
|---|---|---|
| MCP (JSON-RPC 2.0) | MVP | Claude Desktop, Cursor, MCP clients |
| OpenAI Tool Use | MVP | GPT-4, OpenAI Assistants |
| REST webhook | MVP | Custom agents, LangChain, LlamaIndex |
| LangChain toolkit | v2 | Direct LangChain integration |

---

## 7. Playground

The **Playground** is a built-in chat interface in the Elliot platform where you can test your Connector with a real AI agent (powered by Claude) before publishing.

In the Playground you can:
- Chat naturally and watch the agent use your tools in real time
- Inspect every tool call and its result
- Identify gaps (tools that are missing, poorly described, or returning too much data)
- Iterate on tool descriptions and prompts without leaving the platform
- Save successful conversations as few-shot examples for your Prompts

The Playground is the tightest feedback loop in Elliot — build → test → refine, all in one place.

---

## Concept Relationships

```
Product
  └── Endpoints (imported)
       └── Tools (built from endpoints)
            └── Skills (composed from tools)
                 └── Connector (packages tools + skills + prompts)
                      └── Playground (test the connector)
                           └── AI Agent (consumes the connector)
```

A product can have many tools. A skill references multiple tools. A connector packages a selection of tools and skills. Multiple connectors can be built from the same product (e.g., a "read-only" connector and a "full-access" connector).
