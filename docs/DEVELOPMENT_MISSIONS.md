# Elliot — Development Missions

## Overview

The MVP is broken into 12 sequential missions. Each mission produces working, testable functionality. Missions must be completed in order — each builds on the previous.

**Total estimated time**: 80–110 hours
**Critical path**: Mission 1 → 2 → 3 → 4 → 5 → 7 → 9

---

## Mission 1: Foundation — Auth, Layout, Design System
**Estimated**: 4–6 hours | **Dependencies**: None

### Objective
Set up the Next.js 15 project with Supabase authentication, routing structure, and the complete design system.

### Steps

**1.1 Project initialization**
- Create Next.js 15 project with TypeScript and App Router
- Install core dependencies: Tailwind CSS, shadcn/ui, Supabase client, Zod, React Hook Form, SWR
- Configure `tailwind.config.ts` with Elliot design tokens (primary `#0f172a`, accent `#6366f1`, dark mode)
- Set up absolute imports and path aliases

**1.2 Supabase setup**
- Initialize Supabase project
- Run initial schema: `profiles` table + RLS policies
- Set up Supabase client (browser + server components)
- Configure environment variables

**1.3 Authentication pages**
- `/login` — email/password form with Supabase Auth
- `/signup` — registration form with profile creation
- `/auth/callback` — OAuth callback handler
- Auth middleware protecting all `/dashboard`, `/products`, `/tools`, `/connectors` routes

**1.4 Layout components**
- `AppShell` — main layout with sidebar navigation
- `Sidebar` — nav items: Dashboard, Products, Tools, Skills, Prompts, Connectors
- `Header` — user avatar, account dropdown, notifications placeholder
- Responsive: collapsible sidebar on mobile

**1.5 Design system**
- Install and configure shadcn/ui components: Button, Card, Input, Select, Textarea, Badge, Tabs, Dialog, Toast
- Create `Elliot` theme: dark-first, indigo accent
- Typography scale and spacing tokens

### Acceptance Criteria
- User can sign up, log in, and log out
- Protected routes redirect unauthenticated users to `/login`
- Authenticated users land on `/dashboard`
- Layout renders correctly on mobile and desktop

---

## Mission 2: Dashboard
**Estimated**: 3–4 hours | **Dependencies**: Mission 1

### Objective
Build the dashboard with real stats, a getting-started guide, and quick-action buttons.

### Steps

**2.1 Stats cards**
- Products count, Tools count, Skills count, Active Connectors count
- Fetch from Supabase with SWR
- Loading skeleton states

**2.2 Getting started guide**
- Step-by-step checklist: Register Product → Import Endpoints → Create Tool → Build Connector → Connect Agent
- Mark steps complete based on user's actual data

**2.3 Recent activity feed**
- Last 10 tool invocations from `audit_logs`
- Tool name, connector, timestamp, success/failure badge

**2.4 Quick actions**
- "Register your first product" CTA when no products exist
- "Create a tool" and "Build a connector" shortcuts

### Acceptance Criteria
- All stats reflect real data from Supabase
- Getting-started checklist updates as user completes steps
- Activity feed populates after tools are invoked (in later missions)

---

## Mission 3: Product Registration & Endpoint Import
**Estimated**: 10–12 hours | **Dependencies**: Mission 2

### Objective
Allow users to register their existing products and import their API endpoints from OpenAPI specs or Postman collections.

### Steps

**3.1 Product registration form**
- Fields: Name, Base URL, Description
- Auth type selector: None / API Key / Bearer Token / Basic Auth
- Auth config sub-form per type (header name, value for API key; prefix for Bearer; username+password for Basic)
- Credentials stored via Supabase Vault (never in plaintext)
- Validate base URL (reachability check + SSRF protection)

**3.2 OpenAPI importer**
- Accept URL or file upload (.json, .yaml, max 5MB)
- Parse spec using `openapi-typescript` or a custom parser
- Extract all paths × methods as `ParsedEndpoint` objects
- Show preview: "Found 47 endpoints across 8 tags — import all?"
- Bulk insert into `endpoints` table

**3.3 Postman collection importer**
- Accept Postman Collection v2.1 JSON file upload
- Extract requests as endpoints
- Map Postman variables to path params

**3.4 Manual endpoint entry**
- Form: Method selector, Path input, Summary, Description
- Dynamic parameter builder: add path params, query params
- Body schema input (JSON paste or visual form builder, basic version)
- Save to `endpoints`

**3.5 Endpoint browser**
- `/products/[id]/endpoints` — list all imported endpoints
- Filter by HTTP method, tag/group
- Search by path or summary
- "Create Tool from this endpoint" button on each row

**3.6 Product settings**
- Edit base URL, auth config
- Re-import (merge, not replace) endpoints
- Archive product

### Acceptance Criteria
- User can register a product with encrypted credentials
- OpenAPI spec import populates all endpoints correctly
- Postman import works for v2.1 collections
- Manual endpoint entry saves correctly
- Endpoints are listed and filterable

---

## Mission 4: Tool Builder
**Estimated**: 12–14 hours | **Dependencies**: Mission 3

### Objective
Build the complete visual Tool builder — the core value-creation feature of Elliot.

### Steps

**4.1 Tool Builder page structure**
- Multi-section form (not multi-step wizard — all sections visible, scroll-based):
  - Basic Info
  - Endpoint Selection
  - Parameter Mapping
  - Response Configuration
  - Test Runner

**4.2 Basic info section**
- Tool name (auto-generated from endpoint, editable)
- Description (critical — explain to AI when to use this)
- Category: READ / ACTION / MIXED

**4.3 Endpoint selection**
- Dropdown or search to select from user's imported endpoints
- Show endpoint method, path, and description after selection
- Display all endpoint parameters (path, query, body)

**4.4 Parameter mapper**
- For each endpoint parameter: show name, type, required status
- User decides: "Agent-provided" (AI fills this in) or "Forced value" (always this value)
- For agent-provided: set description and optionally a default value
- For forced: set the static value
- Add/remove "virtual" parameters not in the original endpoint (for AI context enrichment)

**4.5 Response configuration**
- Show detected response fields from endpoint schema
- Checkbox list: which fields to include in tool output
- Rename field aliases
- Set `max_items` for array responses

**4.6 Tool test runner**
- Form auto-populated with all agent-provided parameters
- User fills in test values
- "Run Test" → proxy call through Platform API → Connector Runtime
- Show raw response and mapped output side by side
- Show latency

**4.7 Save and list**
- Save tool to Supabase
- Tools list page: name, category, product, endpoint, enabled toggle, invocation count, last used
- Enable/disable toggle (disabled tools hidden from agents)
- Delete with confirmation

### Acceptance Criteria
- User can create a complete tool from an imported endpoint
- All parameter types (path, query, body) can be mapped
- Forced and agent-provided parameters both work correctly
- Test runner calls the real endpoint and shows results
- Tool is listed and can be enabled/disabled

---

## Mission 5: AI-Assisted Tool Generation
**Estimated**: 6–8 hours | **Dependencies**: Mission 4

### Objective
Let users describe a tool in natural language and have AI generate the full configuration.

### Steps

**5.1 AI Tool Generator UI**
- "Generate with AI" tab alongside the manual builder
- Textarea: "Describe what this tool should do"
- Product selector (which product to generate for)
- Optional: select specific endpoint (or let AI pick)
- Show daily quota: `X / 10 AI generations used today`

**5.2 Endpoint matching**
- Send user description + list of endpoint summaries to Claude
- Claude identifies the best-matching endpoint with confidence score
- Display match: "I'll use `GET /v1/customers/{id}` — does this look right?"
- User can override the endpoint selection

**5.3 Tool config generation**
- Send endpoint schema + user description to Claude
- Claude generates: name, description, parameter_config, response_config
- Display generated config in a preview card
- User can edit any field before saving

**5.4 AI Skill Generator**
- Similarly, "Describe a multi-step workflow" → AI generates skill step sequence
- Identifies which tools to chain and the data bindings

**5.5 Quota tracking**
- Track in `ai_usage` table (per user per day, max 10)
- Block generation if quota exceeded; show reset time

### Acceptance Criteria
- AI generates a valid, usable tool config from a plain-English description
- Endpoint matching is accurate for well-described tools
- AI generation quota is enforced
- Generated config can be reviewed and edited before saving

---

## Mission 6: Skill Builder
**Estimated**: 10–12 hours | **Dependencies**: Mission 4

### Objective
Build the Skill composer — the feature that enables multi-step AI workflows.

### Steps

**6.1 Skill Builder page**
- Step list on left, step config panel on right
- Add step: search and select from user's tools
- Reorder steps via drag-and-drop

**6.2 Skill-level inputs**
- Define input parameters at the skill level (what the agent provides)
- Name, type, required, description for each

**6.3 Data binding UI**
- For each step's input fields: show the field name and a binding selector
- Binding options:
  - Fixed value
  - From skill input: `{{skill.input.PARAM_NAME}}`
  - From previous step: `{{steps.ALIAS.FIELD_PATH}}`
- Visual autocomplete for available bindings

**6.4 Step output alias**
- Each step gets an alias name (used in bindings for subsequent steps)
- Auto-named "step_1", "step_2", etc. but user can rename

**6.5 Skill test runner**
- Form with all skill-level input parameters
- "Run Skill" → execute all steps in sequence
- Show step-by-step results panel: each step's inputs, output, and latency
- If a step fails, show which step and why

**6.6 Save and list**
- Save skill to Supabase
- Skills list with step count, product, invocation count
- Enable/disable toggle

### Acceptance Criteria
- User can compose 2–5 tools into a skill
- Data binding with `{{skill.input.X}}` and `{{steps.ALIAS.FIELD}}` works
- Skill test runner executes all steps and shows intermediate results
- Invalid bindings (referencing non-existent fields) show validation errors

---

## Mission 7: Prompt Manager
**Estimated**: 3–4 hours | **Dependencies**: Mission 1

### Objective
Allow users to create and manage system prompts and prompt templates for their connectors.

### Steps

**7.1 Prompt list page**
- `/prompts` — list all prompts with type badge (system/template/few_shot)
- Filter by product, type

**7.2 Prompt editor**
- Monaco-like editor or styled textarea
- Syntax highlighting for `{{variable}}` markers
- Variable extraction: auto-detect `{{VAR}}` patterns and list the required variables
- Character/token count estimate

**7.3 Prompt types**
- `system`: plain text system prompt
- `template`: text with `{{variable}}` substitution; preview with sample values
- `few_shot`: structured Q&A pairs (add pair UI)

**7.4 Link to products**
- Each prompt is scoped to a product
- Product context auto-injected into system prompts during Playground (product name, base URL domain)

### Acceptance Criteria
- User can create, edit, and delete prompts of each type
- Variables are auto-detected and listed
- Templates render correctly with sample values in preview

---

## Mission 8: Connector Packager
**Estimated**: 6–8 hours | **Dependencies**: Missions 4, 6, 7

### Objective
Allow users to package their Tools, Skills, and Prompts into a deployable Connector.

### Steps

**8.1 Connector creation form**
- Name, slug (auto-generated from name, editable), description
- Product selector

**8.2 Content selector**
- Searchable multi-select for Tools (from selected product)
- Searchable multi-select for Skills
- Searchable multi-select for Prompts
- Show counts: "12 tools, 3 skills, 2 prompts selected"

**8.3 Access control**
- Radio: API Key / Public
- Explain implications of public access

**8.4 Deploy / undeploy**
- "Deploy Connector" button → sets status to `active`, records `deployed_at`
- "Undeploy" button → sets status to `draft`
- Deployed connectors get a live `connector_url`

**8.5 API key management**
- "Generate API Key" → generates `sk-ell-` prefixed key, shows it ONCE, stores hash
- List existing keys: name, prefix, last used, created date
- Revoke key button

**8.6 Connection instructions**
- After deploying, show connection instructions for:
  - Claude Desktop (`claude_desktop_config.json` snippet)
  - Cursor (MCP server config snippet)
  - OpenAI (function array snippet)
  - REST (curl example)
- Copy-to-clipboard for each snippet

### Acceptance Criteria
- User can package any combination of tools, skills, prompts into a connector
- Deploying creates a live connector URL
- API keys can be generated and revoked
- Connection instructions are accurate and copy correctly

---

## Mission 9: Connector Runtime (Python FastAPI)
**Estimated**: 16–20 hours | **Dependencies**: Missions 4, 6, 8

### Objective
Build the Connector Runtime — the Python FastAPI service that AI agents actually talk to.

### Steps

**9.1 Project setup**
- Python 3.11+ FastAPI project
- Dependencies: fastapi, uvicorn, httpx, supabase-py, pydantic, bcrypt, python-jose, slowapi
- Dockerfile for containerized deployment
- Config management via environment variables

**9.2 API key authentication**
- Extract `Authorization: Bearer sk-ell-...` header
- Look up key_prefix in `api_keys` table
- bcrypt verify against `key_hash`
- Cache validated keys in memory (TTL: 300s) to avoid bcrypt overhead on every request
- Rate limiting via `slowapi` (per connector, configurable)

**9.3 Connector loader**
- Fetch connector config from Supabase on first request (by slug)
- Deserialize: connector metadata + tool configs + skill configs + product auth config
- In-memory cache (key: connector_id + version, TTL: 60s)
- Cache invalidated via admin endpoint called on connector deploy

**9.4 MCP protocol handler** (`/mcp/{slug}`)
- Parse JSON-RPC 2.0 request
- Route to: `initialize`, `tools/list`, `tools/call`
- `initialize`: return capabilities and server info
- `tools/list`: return all enabled tools + skills as MCP tool definitions (with JSON schema)
- `tools/call`: validate + execute + return MCP content response

**9.5 Tool executor**
- Build HTTP request from tool config + agent arguments:
  - Resolve path params (replace `{param}` in path)
  - Attach query params
  - Build request body from body params
- Inject product authentication (via Vault)
- Execute with `httpx.AsyncClient` (timeout: 30s)
- Handle HTTP errors (4xx, 5xx → return structured error to agent)
- Apply response_config (field filtering, renaming, max_items)

**9.6 Skill runner (sequential)**
- Iterate steps in order
- Resolve `{{skill.input.X}}` and `{{steps.ALIAS.FIELD}}` bindings using jsonpath
- Execute each step's tool
- Store output under alias
- Return consolidated result

**9.7 OpenAI format handler** (`/openai/{slug}/...`)
- `GET /openai/{slug}/tools` → OpenAI function-calling format
- `POST /openai/{slug}/call/{name}` → execute tool, return raw JSON

**9.8 REST handler** (`/rest/{slug}/tools/{name}`)
- Accept plain JSON body as tool parameters
- Return plain JSON result (no MCP envelope)

**9.9 Audit logging**
- After every tool/skill call: INSERT into `audit_logs` (async, fire-and-forget)
- Log: connector_id, api_key_id, tool/skill name, parameters, response_summary, latency_ms, success

**9.10 Health and admin**
- `GET /health` → `{ status: "healthy" }`
- `POST /admin/cache/invalidate?connector_id=...` → clear cached connector (authenticated with shared secret)

### Acceptance Criteria
- Claude Desktop can connect to the runtime and list tools
- Tool calls execute against user's real API and return correct results
- Skill calls execute all steps in order with correct data passing
- Rate limiting blocks requests exceeding the configured limit
- Audit logs are created for every invocation
- Unauthorized requests return 401

---

## Mission 10: Agent Playground
**Estimated**: 8–10 hours | **Dependencies**: Missions 8, 9

### Objective
Build the in-platform playground where users test their connector by chatting with a real Claude agent.

### Steps

**10.1 Playground UI**
- `/connectors/[id]/playground`
- Split pane: chat on left, tool call inspector on right
- Chat input at bottom, conversation history above

**10.2 Streaming chat backend**
- `POST /api/connectors/[id]/playground` → streaming response
- Load connector's tools in Claude tool-use format
- Build system prompt from connector's linked prompts
- Stream Claude response to client via Server-Sent Events

**10.3 Tool call interception**
- When Claude makes a tool call: pause stream, proxy to Connector Runtime, feed result back
- Add tool call event to inspector panel in real time

**10.4 Inspector panel**
- Expandable list of all tool calls in current session
- For each call: tool name, arguments (JSON), result (JSON), latency
- Click a call → open tool editor in side sheet (edit description, re-test)

**10.5 Playground state management**
- Session reset button (clear conversation, keep tools)
- Export conversation as few-shot example → adds to Prompts

### Acceptance Criteria
- User can type a message and Claude responds using their connector tools
- Every tool call appears in the inspector panel with full detail
- Editing a tool description from the inspector takes effect immediately
- Conversation can be reset without leaving the page

---

## Mission 11: Analytics & Monitoring
**Estimated**: 4–5 hours | **Dependencies**: Mission 9

### Objective
Build analytics views showing connector usage, tool performance, and error rates.

### Steps

**11.1 Connector analytics page**
- `/connectors/[id]/analytics`
- Total invocations (7d, 30d), success rate, average latency
- Line chart: invocations per day over 30 days
- Top tools by invocation count
- Error rate per tool

**11.2 Tool-level stats**
- On tool detail page: execution count, last executed, success rate, avg latency

**11.3 Audit log viewer**
- Raw audit log table with filters: date range, tool, success/failure
- Expand row: full parameters and response summary

**11.4 Dashboard stats refresh**
- Connect dashboard stats cards to real data (from Missions above)

### Acceptance Criteria
- Analytics show accurate data from audit_logs
- Charts render correctly with 30 days of data
- Audit log table is filterable and paginated

---

## Mission 12: Error Handling, Polish & Deployment
**Estimated**: 8–10 hours | **Dependencies**: All previous missions

### Objective
Production-harden the application: comprehensive error handling, deployment configuration, and monitoring setup.

### Steps

**12.1 Error boundaries**
- React error boundaries on all major page sections
- User-friendly fallback UI with retry options

**12.2 Form validation hardening**
- Zod schemas for all forms, synchronized between client and API routes
- Clear, specific validation messages (not "field is required" — "Tool name must start with a verb like get_, create_, or list_")

**12.3 Loading states**
- Skeleton loaders for all data-fetching sections
- Optimistic UI updates for toggle switches

**12.4 Empty states**
- Helpful empty states on every list page with clear CTAs
- No "No data found" — instead "You haven't created any tools yet. Start by registering a product."

**12.5 Frontend deployment (Vercel)**
- Connect GitHub repo to Vercel
- Set all environment variables
- Configure production domain
- Test all pages in production environment

**12.6 Runtime deployment (Railway)**
- Dockerize the Connector Runtime
- Deploy to Railway with environment variables
- Set up health check and auto-restart
- Configure production domain (`runtime.elliot.ai`)

**12.7 Database migrations**
- Final schema review
- Run all migrations against production Supabase
- Verify RLS policies work correctly in production

**12.8 Monitoring**
- Set up Sentry for error tracking (both Next.js and FastAPI)
- Set up Uptime monitoring for runtime health endpoint
- Add structured logging to runtime (JSON format, indexed fields)

### Acceptance Criteria
- All known error paths have user-friendly handling
- Application deploys successfully to Vercel + Railway
- Sentry captures errors from both services
- Health check endpoint returns 200 in production
- End-to-end flow works: register product → import endpoints → create tool → deploy connector → connect Claude Desktop → invoke tool

---

## Mission Summary

| # | Mission | Time | Key Output |
|---|---|---|---|
| 1 | Foundation | 4–6h | Auth + layout + design system |
| 2 | Dashboard | 3–4h | Stats + activity + quick actions |
| 3 | Product Registration + Import | 10–12h | OpenAPI import + endpoint browser |
| 4 | Tool Builder | 12–14h | Visual tool creation + test runner |
| 5 | AI Tool Generation | 6–8h | Natural language → tool config |
| 6 | Skill Builder | 10–12h | Multi-step workflow composer |
| 7 | Prompt Manager | 3–4h | System prompts + templates |
| 8 | Connector Packager | 6–8h | Deploy connector + API keys |
| 9 | Connector Runtime | 16–20h | MCP server + tool/skill executor |
| 10 | Agent Playground | 8–10h | Chat-based connector testing |
| 11 | Analytics | 4–5h | Usage charts + audit logs |
| 12 | Polish + Deploy | 8–10h | Production-ready deployment |

**Total**: 90–113 hours

### Recommended Parallel Work

These missions can overlap once their dependencies are met:

- Mission 7 (Prompts) can be built alongside Mission 5 or 6
- Mission 11 (Analytics) can be built alongside Mission 10
- Mission 9 (Runtime) development can start as soon as Mission 4 is done, before Mission 8
