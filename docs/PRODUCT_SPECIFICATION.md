# Elliot — Product Specification (MVP)

## Executive Summary

Elliot is a platform that turns any existing product (REST APIs, databases, action endpoints) into an AI-native **Connector** — a structured, deployable interface that AI agents can discover, understand, and interact with. Teams use Elliot to create Tools, Skills, and Prompts on top of their existing infrastructure, then expose everything through a single Connector URL that any MCP-compatible agent can use.

---

## 1. Problem Statement

### The Gap Between Products and AI Agents

- Every modern product has APIs. Almost none of them are agent-ready.
- Agents need more than endpoints: they need semantic descriptions, parameter typing, response shaping, and workflow knowledge.
- Building a custom MCP server or AI integration from scratch takes days/weeks of engineering work per product.
- Non-technical teams (product, ops, support) can't participate in AI integration work at all today.
- Even technical teams face repetition: every product needs the same scaffolding rebuilt from scratch.

### Who Feels This Pain

| Persona | Pain |
|---|---|
| SaaS company | Wants to offer AI integrations for customers but can't afford to build custom MCP servers |
| Internal tool team | Has internal APIs they want exposed to AI agents for automation |
| Integration engineer | Rebuilds the same tool-wrapping boilerplate for every client project |
| Product manager | Has a vision for AI features but can't ship without engineering help |

---

## 2. Solution

Elliot provides a **three-layer abstraction** on top of existing products:

1. **Import** — Bring your existing API (via OpenAPI spec, Postman, or manual entry) into Elliot
2. **Build** — Define Tools (atomic operations), Skills (multi-step workflows), and Prompts (AI behavioral guidance) using a visual builder
3. **Deploy** — Package everything as a Connector with a unique URL; AI agents connect and interact

The system is designed to be:
- **Generic** — Works with any product that has HTTP APIs or a database
- **Non-destructive** — Never touches the user's existing product; only wraps it
- **Iterative** — Build incrementally; start with one tool, grow to a full connector
- **AI-assisted** — The platform uses AI to help generate tool configurations from natural language or API specs

---

## 3. MVP Features

### 3.1 Core Features (Must-Have)

#### Product Management
- Register a product with base URL and authentication (API key, OAuth2 header, Basic Auth)
- Import endpoints from an OpenAPI/Swagger spec (URL or file upload)
- Import from Postman collection (JSON upload)
- Manual endpoint entry (method, path, parameters, description)
- View imported endpoints in a structured list with filtering

#### Tool Builder
- Create a Tool from one imported endpoint
- Visual parameter mapper: map endpoint parameters to tool parameters
- Set forced values (parameters that are always sent with a fixed value)
- Set agent-provided parameters (the AI fills these in at runtime)
- Response field selector: choose which fields from the endpoint response to return to the agent
- Tool category: READ or ACTION
- AI-assisted tool generation: describe the tool in natural language, AI maps it to an endpoint
- Test runner: execute the tool against the live endpoint with sample parameters
- Tool list page with enable/disable toggle

#### Skill Builder
- Create a Skill by composing 2–5 Tools in sequence
- Define data bindings between steps using a visual `{{step.output.field}}` mapper
- Skill-level input parameters
- Test runner: execute the full skill with sample inputs
- View intermediate step outputs during testing

#### Prompt Manager
- Create system prompts for a Connector
- Create prompt templates with `{{variable}}` substitution
- Link prompts to a Connector

#### Connector Manager
- Package selected Tools, Skills, and Prompts into a Connector
- Generate a unique Connector URL (`/c/{slug}`)
- Deploy / undeploy a Connector
- Generate API keys for Connector access
- View connection instructions for Claude Desktop, Cursor, and REST clients

#### Agent Playground
- Built-in chat interface using Claude as the agent
- Claude uses the Connector's tools in real time
- Inspect every tool call (name, parameters, result) in a side panel
- Iterate on tool descriptions and test again without leaving the page

#### Analytics
- Tool invocation count (last 7 / 30 days)
- Connector session count
- Last used timestamp per tool

### 3.2 AI Assistance Features
- **AI Tool Generator**: Describe a tool in plain English → AI generates name, description, parameter mapping, and response mapping
- **AI Endpoint Matcher**: Describe what you want to do → AI identifies which imported endpoint matches
- **AI Skill Generator**: Describe a multi-step workflow → AI generates the skill step sequence
- Quota: 10 AI-assisted generations per user per day

### 3.3 Protocol Support (MVP)
- **MCP (JSON-RPC 2.0)**: Full implementation for Claude Desktop, Cursor, and other MCP clients
- **OpenAI Tool Use format**: Export Connector tools in OpenAI function-calling schema
- **REST endpoint**: Simple REST wrapper around each tool for custom integrations

---

## 4. Out of Scope for MVP

These features are intentionally excluded and are planned for future versions.

| Feature | Reason Excluded | Future Plan |
|---|---|---|
| GraphQL support | Requires separate query builder UI | Phase 2 |
| Database direct connection | Adds connection security complexity; APIs cover most use cases | Phase 2 |
| Conditional/branching skills | Adds significant builder UI complexity | Phase 2 |
| AI-orchestrated skills | Runtime LLM cost and latency; sequential is sufficient for MVP | Phase 2 |
| Team collaboration | Single-user connectors cover MVP use cases | Phase 3 |
| Connector marketplace | Needs moderation and discovery infrastructure | Phase 3 |
| OAuth2 connector access | API key is sufficient for MVP; OAuth adds auth flow complexity | Phase 2 |
| Versioned connector deployment | Single deployed version per connector for MVP | Phase 2 |
| Webhook triggers (inbound) | Agents calling Elliot based on product events | Phase 3 |
| Custom code execution | Security complexity; config-driven approach sufficient for MVP | Phase 3 |
| Real-time streaming responses | Most tool calls complete in <2s; streaming is premature | Phase 2 |

---

## 5. User Stories

### Product Registration
- As a user, I can paste an OpenAPI spec URL and Elliot imports all my endpoints automatically
- As a user, I can upload a Postman collection JSON to import my API
- As a user, I can manually add an endpoint with method, path, and parameters
- As a user, I can edit the authentication settings for my product

### Tool Building
- As a user, I can select an endpoint and create an AI Tool from it in under 2 minutes
- As a user, I can ask AI to generate a tool by describing what I want in plain English
- As a user, I can test my tool against my live API from within Elliot before deploying
- As a user, I can mark some parameters as agent-controlled and others as fixed values

### Skill Building
- As a user, I can chain two or more Tools into a Skill with a visual step builder
- As a user, I can map output from Step 1 as input to Step 2 using a visual binding interface
- As a user, I can test my Skill end-to-end with sample input from within Elliot

### Connector Management
- As a user, I can package my Tools and Skills into a named Connector
- As a user, I can deploy my Connector and get a unique URL to share with agents
- As a user, I can generate API keys for agent access and revoke them
- As a user, I can see exactly how to connect Claude Desktop to my Connector

### Playground
- As a user, I can chat with Claude in the Playground and watch it use my tools in real time
- As a user, I can see each tool call and its result in the Playground side panel
- As a user, I can click a tool call to edit the tool's description and re-test immediately

### Analytics
- As a user, I can see how many times each tool was called in the last 30 days
- As a user, I can see which agents are connecting to my Connector

---

## 6. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Tool execution latency (p95) | < 3 seconds (excluding user's own API latency) |
| Connector uptime | 99.9% |
| AI generation response time | < 10 seconds |
| Max tool parameters | 20 per tool |
| Max skill steps | 10 per skill |
| Max tools per connector | 50 |
| Max API key length | 64 chars |
| File upload for OpenAPI spec | Max 5MB |
| Connector URL uniqueness | Globally unique slug |

---

## 7. Success Metrics

### Activation
- % of users who create at least one Tool (target: 60% within 1 week of signup)
- % of users who deploy at least one Connector (target: 40%)
- Time from signup to first deployed Connector (target: < 30 minutes)

### Engagement
- Average Tools per active user
- Average Playground sessions per week
- % of tools created with AI assistance

### Performance
- Tool invocation success rate (target: > 95%)
- Average tool execution latency
- AI generation success rate (valid config produced)

### Retention
- 7-day retention
- 30-day retention
- Weekly active connectors (connectors with at least 1 invocation)
