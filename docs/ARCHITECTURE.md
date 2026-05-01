# Elliot — Technical Architecture

## 1. System Overview

Elliot has three distinct runtime zones:

```
┌─────────────────────────────────────────────────────────────────┐
│                     ZONE 1 — AI CLIENTS                         │
│   Claude Desktop · Cursor · Custom Agents · Any MCP Client      │
└────────────────────────┬────────────────────────────────────────┘
                         │  MCP (JSON-RPC 2.0) / OpenAI Tools / REST
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              ZONE 2 — CONNECTOR RUNTIME (Python / FastAPI)       │
│                                                                  │
│  ┌────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  Auth & Rate   │  │  Tool Executor  │  │ Skill Runner    │  │
│  │  Limiting      │  │  (HTTP proxy)   │  │ (step engine)   │  │
│  └────────────────┘  └─────────────────┘  └─────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Connector Config Cache  ←──→  Supabase                  │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │  HTTPS → user's real APIs
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              ZONE 3 — USER'S EXISTING PRODUCT                    │
│              REST APIs · Databases · Action Endpoints            │
└─────────────────────────────────────────────────────────────────┘

          ╔═══════════════════════════════════╗
          ║  ELLIOT PLATFORM (Next.js + API)  ║
          ║  Where users build connectors     ║
          ╚═══════════╤═══════════════════════╝
                      │ CRUD config via Supabase
                      ▼
              ┌───────────────┐
              │   Supabase    │
              │ PostgreSQL    │
              │ Auth          │
              │ Storage       │
              └───────────────┘
```

The **Elliot Platform** (web app) is where users build. The **Connector Runtime** is what agents actually talk to. These are separate deployed services that share the Supabase database.

---

## 2. Component Architecture

### 2.1 Elliot Platform (Next.js 15)

The web application users interact with to build their connectors.

**App Router pages:**
```
/
├── /login
├── /signup
├── /dashboard
├── /products
│   ├── /new                     ← register a product
│   └── /[id]
│       ├── /endpoints            ← view imported endpoints
│       ├── /import               ← import from OpenAPI/Postman
│       └── /settings             ← auth config, base URL
├── /tools
│   ├── /new?product_id=...       ← tool builder
│   └── /[id]
│       ├── /edit
│       └── /test
├── /skills
│   ├── /new?product_id=...       ← skill builder
│   └── /[id]
│       ├── /edit
│       └── /test
├── /prompts
│   ├── /new
│   └── /[id]/edit
├── /connectors
│   ├── /new                     ← package tools + skills
│   └── /[id]
│       ├── /settings             ← access control, API keys
│       ├── /playground           ← chat-based agent testing
│       └── /analytics            ← usage stats
└── /settings                    ← account, billing (future)
```

**Key frontend components:**
- `ProductImporter` — OpenAPI parser, Postman importer, manual endpoint entry
- `EndpointBrowser` — Browse imported endpoints, select one to build a tool from
- `ToolBuilder` — Visual tool configuration (parameter mapping, response shaping)
- `SkillBuilder` — Step composer with visual data binding
- `PromptEditor` — Prompt template editor with variable syntax
- `ConnectorPackager` — Select tools + skills + prompts, set access, deploy
- `Playground` — Chat UI + tool call inspector panel
- `AnalyticsDashboard` — Usage charts and connector health

**State management:**
- React Context for auth state and global config
- SWR for server state (tools, skills, connectors)
- React Hook Form + Zod for all form validation

### 2.2 Platform API (Next.js API Routes)

The backend API for the web application. All routes require authentication (Supabase JWT).

**Route groups:**
```
/api/products/          CRUD for user products
/api/products/[id]/import   Import endpoints from OpenAPI/Postman
/api/endpoints/         CRUD for individual endpoints
/api/tools/             CRUD for tools
/api/tools/[id]/test    Execute tool against live API (proxied)
/api/tools/ai-generate  AI-assisted tool generation
/api/skills/            CRUD for skills
/api/skills/[id]/test   Execute skill against live APIs
/api/skills/ai-generate AI-assisted skill generation
/api/prompts/           CRUD for prompts
/api/connectors/        CRUD for connectors
/api/connectors/[id]/deploy     Deploy/undeploy connector
/api/connectors/[id]/keys       API key management
/api/connectors/[id]/playground Playground chat (streams)
/api/ai/generate        AI generation quota check + call
/api/analytics/         Usage stats queries
```

### 2.3 Connector Runtime (Python FastAPI)

The deployed service that AI agents actually talk to. It is **stateless** — it reads all connector configuration from Supabase and executes tool calls against the user's real APIs.

**Runtime responsibilities:**
1. Authenticate incoming agent requests (validate API keys)
2. Load connector configuration from Supabase (with in-memory cache, TTL 60s)
3. Expose the connector's tools and skills via MCP / OpenAI / REST protocols
4. When a tool is called: validate parameters → inject product auth → proxy HTTP call to user's API → map response → return to agent
5. When a skill is called: execute step sequence → pass data between steps → return final result
6. Rate limiting (per connector, per API key)
7. Write audit log entry for every tool/skill invocation

**Runtime module structure:**
```
connector-runtime/
├── main.py                    ← FastAPI app, route definitions
├── config.py                  ← Settings (env vars)
├── protocols/
│   ├── mcp.py                 ← JSON-RPC 2.0 handler
│   ├── openai.py              ← OpenAI tool format handler
│   └── rest.py                ← Simple REST handler
├── auth/
│   ├── api_key.py             ← API key validation
│   └── rate_limiter.py        ← Per-key rate limiting
├── connector/
│   ├── loader.py              ← Load + cache connector config from Supabase
│   ├── registry.py            ← Tool and skill registry for a connector
│   └── schema_generator.py   ← Generate JSON schemas for MCP/OpenAI
├── executor/
│   ├── tool_executor.py       ← Execute a single tool (HTTP proxy)
│   ├── skill_runner.py        ← Execute a multi-step skill
│   ├── auth_injector.py       ← Inject product credentials into requests
│   ├── param_validator.py     ← Validate agent-provided parameters
│   └── response_mapper.py     ← Map API response to tool output
├── audit/
│   └── logger.py              ← Write audit logs to Supabase
└── requirements.txt
```

---

## 3. Data Model

### 3.1 Entity Relationship

```
auth.users (Supabase)
    │
    ├──< products >──< endpoints
    │       │
    │       ├──< tools >──────────────────┐
    │       ├──< skills (steps: tool[])   │
    │       └──< prompts                  │
    │                                     │
    └──< connectors >──────────────────< connector_tools (tool_ids[])
              │                         connector_skills (skill_ids[])
              │                         connector_prompts (prompt_ids[])
              ├──< connector_versions
              ├──< api_keys
              └──< audit_logs
```

### 3.2 Schema

```sql
-- ─────────────────────────────────────────────
-- PRODUCTS
-- ─────────────────────────────────────────────
CREATE TABLE products (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  description   TEXT,
  base_url      TEXT NOT NULL,

  -- Authentication config (stored encrypted via Supabase Vault)
  auth_type     TEXT NOT NULL DEFAULT 'none'
                  CHECK (auth_type IN ('none','api_key','bearer','basic','oauth2_header')),
  auth_config   JSONB,
  -- auth_config examples:
  --   api_key: { "header": "X-API-Key", "value_secret_id": "<vault_id>" }
  --   bearer:  { "header": "Authorization", "prefix": "Bearer", "value_secret_id": "<vault_id>" }
  --   basic:   { "username_secret_id": "<vault_id>", "password_secret_id": "<vault_id>" }

  import_source TEXT CHECK (import_source IN ('openapi','postman','manual')),
  import_url    TEXT,          -- URL of OpenAPI spec (if imported from URL)

  status        TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','error','archived')),
  error_message TEXT,

  created_at    TIMESTAMPTZ DEFAULT NOW(),
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- ENDPOINTS (imported from product API)
-- ─────────────────────────────────────────────
CREATE TABLE endpoints (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

  method          TEXT NOT NULL CHECK (method IN ('GET','POST','PUT','PATCH','DELETE')),
  path            TEXT NOT NULL,             -- e.g., /v1/customers/{id}
  summary         TEXT,                      -- short one-liner
  description     TEXT,                      -- longer description
  tags            TEXT[],                    -- grouping tags

  -- Structured parameter definitions
  path_params     JSONB DEFAULT '[]',        -- [{ name, type, required, description }]
  query_params    JSONB DEFAULT '[]',
  body_schema     JSONB,                     -- JSON Schema of request body
  response_schema JSONB,                     -- JSON Schema of successful response

  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- TOOLS
-- ─────────────────────────────────────────────
CREATE TABLE tools (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  endpoint_id     UUID REFERENCES endpoints(id) ON DELETE SET NULL,

  name            TEXT NOT NULL,          -- snake_case, globally unique per user
  description     TEXT NOT NULL,          -- the AI reads this to decide when to call the tool
  category        TEXT NOT NULL DEFAULT 'READ'
                    CHECK (category IN ('READ','ACTION','MIXED')),

  -- Parameter configuration
  parameter_config JSONB NOT NULL DEFAULT '[]',
  -- [
  --   {
  --     "name": "customer_id",
  --     "type": "string",
  --     "description": "...",
  --     "required": true,
  --     "source": "agent",            -- "agent" | "forced"
  --     "forced_value": null,         -- used when source = "forced"
  --     "maps_to": "path_params.id"   -- which endpoint param this maps to
  --   }
  -- ]

  -- Response configuration
  response_config JSONB NOT NULL DEFAULT '{}',
  -- {
  --   "include_fields": ["id", "name", "email"],  -- null means all fields
  --   "rename": { "customerId": "id" },
  --   "max_items": 100
  -- }

  enabled         BOOLEAN NOT NULL DEFAULT true,
  execution_count INTEGER NOT NULL DEFAULT 0,
  last_executed_at TIMESTAMPTZ,

  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(user_id, name)
);

-- ─────────────────────────────────────────────
-- SKILLS
-- ─────────────────────────────────────────────
CREATE TABLE skills (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  product_id          UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,

  name                TEXT NOT NULL,
  description         TEXT NOT NULL,
  category            TEXT,

  -- Input parameters at the skill level (before step 1)
  input_parameters    JSONB NOT NULL DEFAULT '[]',
  -- [{ name, type, description, required }]

  -- Orchestration mode
  orchestration_mode  TEXT NOT NULL DEFAULT 'sequential'
                        CHECK (orchestration_mode IN ('sequential','conditional','ai_orchestrated')),

  -- Step definitions (sequential mode)
  steps               JSONB NOT NULL DEFAULT '[]',
  -- [
  --   {
  --     "step_id": "step_1",
  --     "tool_id": "<uuid>",
  --     "output_alias": "customer",
  --     "input_bindings": {
  --       "customer_id": "{{skill.input.id}}",
  --       "status": "active"
  --     }
  --   },
  --   {
  --     "step_id": "step_2",
  --     "tool_id": "<uuid>",
  --     "output_alias": "subscription",
  --     "input_bindings": {
  --       "customer_id": "{{steps.customer.id}}"
  --     }
  --   }
  -- ]

  -- For ai_orchestrated mode: the planning prompt
  orchestration_prompt TEXT,

  enabled             BOOLEAN NOT NULL DEFAULT true,
  execution_count     INTEGER NOT NULL DEFAULT 0,

  created_at          TIMESTAMPTZ DEFAULT NOW(),
  updated_at          TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(user_id, name)
);

-- ─────────────────────────────────────────────
-- PROMPTS
-- ─────────────────────────────────────────────
CREATE TABLE prompts (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  product_id  UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,

  name        TEXT NOT NULL,
  type        TEXT NOT NULL CHECK (type IN ('system','template','few_shot')),
  content     TEXT NOT NULL,    -- the prompt text; templates use {{variable}} syntax
  variables   TEXT[],           -- list of variable names referenced in content
  tags        TEXT[],

  created_at  TIMESTAMPTZ DEFAULT NOW(),
  updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- CONNECTORS
-- ─────────────────────────────────────────────
CREATE TABLE connectors (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  product_id    UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,

  name          TEXT NOT NULL,
  slug          TEXT NOT NULL UNIQUE,   -- URL-safe identifier, globally unique
  description   TEXT,
  version       TEXT NOT NULL DEFAULT '1.0.0',

  -- Packaged content (arrays of UUIDs)
  tool_ids      UUID[] NOT NULL DEFAULT '{}',
  skill_ids     UUID[] NOT NULL DEFAULT '{}',
  prompt_ids    UUID[] NOT NULL DEFAULT '{}',

  -- Access control
  access_type   TEXT NOT NULL DEFAULT 'api_key'
                  CHECK (access_type IN ('api_key','public','oauth')),

  -- Deployment state
  status        TEXT NOT NULL DEFAULT 'draft'
                  CHECK (status IN ('draft','active','deprecated')),
  deployed_at   TIMESTAMPTZ,
  connector_url TEXT GENERATED ALWAYS AS
                  ('https://runtime.elliot.ai/c/' || slug) STORED,

  created_at    TIMESTAMPTZ DEFAULT NOW(),
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- CONNECTOR VERSIONS (snapshot history)
-- ─────────────────────────────────────────────
CREATE TABLE connector_versions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  connector_id  UUID NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
  version       TEXT NOT NULL,
  snapshot      JSONB NOT NULL,  -- full serialized connector config at time of deploy
  is_current    BOOLEAN NOT NULL DEFAULT false,
  deployed_by   UUID REFERENCES auth.users(id),
  deployed_at   TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(connector_id, version)
);

-- ─────────────────────────────────────────────
-- API KEYS (for connector access)
-- ─────────────────────────────────────────────
CREATE TABLE api_keys (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  connector_id  UUID NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
  user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

  name          TEXT NOT NULL,          -- user-given label, e.g. "Claude Desktop key"
  key_prefix    TEXT NOT NULL,          -- first 8 chars, for display: "sk-ell-xxxx..."
  key_hash      TEXT NOT NULL,          -- bcrypt hash of the full key
  last_used_at  TIMESTAMPTZ,
  expires_at    TIMESTAMPTZ,

  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- AUDIT LOGS
-- ─────────────────────────────────────────────
CREATE TABLE audit_logs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  connector_id    UUID REFERENCES connectors(id) ON DELETE SET NULL,
  api_key_id      UUID REFERENCES api_keys(id) ON DELETE SET NULL,
  tool_id         UUID REFERENCES tools(id) ON DELETE SET NULL,
  skill_id        UUID REFERENCES skills(id) ON DELETE SET NULL,

  session_id      TEXT,                 -- groups tool calls within an agent session
  method          TEXT NOT NULL,        -- 'tools/call' | 'skills/call' | 'tools/list'
  entity_name     TEXT,                 -- tool or skill name

  parameters      JSONB,
  response_summary JSONB,               -- { rows_returned, status_code, truncated }
  latency_ms      INTEGER,
  success         BOOLEAN NOT NULL,
  error_message   TEXT,

  ip_address      TEXT,
  user_agent      TEXT,
  protocol        TEXT,                 -- 'mcp' | 'openai' | 'rest'

  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- AI USAGE TRACKING
-- ─────────────────────────────────────────────
CREATE TABLE ai_usage (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  date              DATE NOT NULL DEFAULT CURRENT_DATE,
  generations_used  INTEGER NOT NULL DEFAULT 0,

  UNIQUE(user_id, date)
);
```

### 3.3 Row Level Security

```sql
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE endpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE tools ENABLE ROW LEVEL SECURITY;
ALTER TABLE skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompts ENABLE ROW LEVEL SECURITY;
ALTER TABLE connectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE connector_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_usage ENABLE ROW LEVEL SECURITY;

-- All user-owned tables follow the same pattern
CREATE POLICY "owner_only" ON products
  FOR ALL USING (auth.uid() = user_id);

-- Same policy applied to: endpoints, tools, skills, prompts,
-- connectors, connector_versions, api_keys, ai_usage

-- Audit logs: owners of the connector can read their logs
CREATE POLICY "connector_owner_reads_logs" ON audit_logs
  FOR SELECT USING (
    connector_id IN (SELECT id FROM connectors WHERE user_id = auth.uid())
  );
```

### 3.4 Performance Indexes

```sql
CREATE INDEX idx_products_user_id ON products(user_id);
CREATE INDEX idx_endpoints_product_id ON endpoints(product_id);
CREATE INDEX idx_tools_user_id ON tools(user_id);
CREATE INDEX idx_tools_product_id ON tools(product_id);
CREATE INDEX idx_tools_enabled ON tools(enabled) WHERE enabled = true;
CREATE INDEX idx_skills_user_id ON skills(user_id);
CREATE INDEX idx_connectors_slug ON connectors(slug);
CREATE INDEX idx_connectors_user_id ON connectors(user_id);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX idx_audit_logs_connector_id ON audit_logs(connector_id);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at DESC);
CREATE INDEX idx_audit_logs_session_id ON audit_logs(session_id);
```

---

## 4. Connector Runtime — Deep Dive

### 4.1 Request Lifecycle (MCP Tool Call)

```
Agent sends:
  POST /mcp/{slug}
  Authorization: Bearer sk-ell-xxxxxxxx
  { "jsonrpc": "2.0", "method": "tools/call",
    "params": { "name": "get_customer", "arguments": { "id": "cust_123" } } }

  Step 1 — Auth
    ├── Extract API key from Authorization header
    ├── Look up key_hash in api_keys table (cached)
    ├── If invalid → return JSON-RPC error -32001 Unauthorized
    └── Resolve connector_id and validate connector is active

  Step 2 — Load Connector Config
    ├── Check in-memory cache (key: connector_id, TTL: 60s)
    ├── If cache miss → fetch from Supabase:
    │     SELECT tools, skills, product (with auth_config) WHERE connector_id = ...
    └── Build tool registry in memory

  Step 3 — Validate Tool Call
    ├── Find tool "get_customer" in registry
    ├── Validate provided arguments against tool's parameter_config
    └── If missing required param → return JSON-RPC error -32602 Invalid params

  Step 4 — Execute Tool
    ├── Resolve endpoint: method=GET, path=/v1/customers/{id}
    ├── Map tool arguments to endpoint parameters:
    │     path: { id: "cust_123" }
    ├── Inject product authentication:
    │     headers: { "X-API-Key": "<decrypted from vault>" }
    ├── Execute HTTP call to user's product:
    │     GET https://api.userproduct.com/v1/customers/cust_123
    │     X-API-Key: ...
    └── Receive response: { "id": "cust_123", "name": "Acme Corp", ... }

  Step 5 — Map Response
    ├── Apply response_config.include_fields filter
    ├── Apply response_config.rename mappings
    └── Apply response_config.max_items truncation

  Step 6 — Audit Log
    └── INSERT into audit_logs (async, non-blocking)

  Step 7 — Return to Agent
    └── { "jsonrpc": "2.0", "result": {
          "content": [{ "type": "text", "text": "{\"id\": \"cust_123\", \"name\": \"Acme Corp\"}" }]
        } }
```

### 4.2 Skill Execution (Sequential Mode)

```python
async def run_skill_sequential(skill_config, input_params, context):
    step_outputs = {}
    
    for step in skill_config["steps"]:
        tool = registry.get_tool(step["tool_id"])
        
        # Resolve input bindings ({{skill.input.X}} and {{steps.ALIAS.FIELD}})
        resolved_inputs = resolve_bindings(
            step["input_bindings"],
            skill_inputs=input_params,
            step_outputs=step_outputs
        )
        
        # Execute tool
        result = await execute_tool(tool, resolved_inputs, context)
        
        # Store output under alias for next steps to reference
        step_outputs[step["output_alias"]] = result
    
    return step_outputs
```

### 4.3 Auth Injection

The runtime reads encrypted product credentials from Supabase Vault and injects them into every outbound HTTP call. This means agent API keys never contain product credentials — they only identify the connector.

```python
class AuthInjector:
    async def inject(self, request: httpx.Request, auth_config: dict) -> httpx.Request:
        auth_type = auth_config["type"]
        
        if auth_type == "api_key":
            secret = await vault.get_secret(auth_config["value_secret_id"])
            request.headers[auth_config["header"]] = secret
            
        elif auth_type == "bearer":
            secret = await vault.get_secret(auth_config["value_secret_id"])
            request.headers["Authorization"] = f"Bearer {secret}"
            
        elif auth_type == "basic":
            username = await vault.get_secret(auth_config["username_secret_id"])
            password = await vault.get_secret(auth_config["password_secret_id"])
            request.headers["Authorization"] = httpx.BasicAuth(username, password)
            
        return request
```

### 4.4 Multi-Protocol Support

```python
# MCP (JSON-RPC 2.0) — Primary protocol
@app.post("/mcp/{slug}")
async def handle_mcp(slug: str, request: Request):
    body = await request.json()
    method = body.get("method")
    
    if method == "initialize":
        return mcp_initialize_response()
    elif method == "tools/list":
        return mcp_list_tools(connector)
    elif method == "tools/call":
        return await mcp_call_tool(connector, body["params"])

# OpenAI Tool Use format
@app.get("/openai/{slug}/tools")
async def openai_tools(slug: str):
    # Returns OpenAI-format tool definitions array
    return {"tools": [to_openai_format(t) for t in connector.tools]}

@app.post("/openai/{slug}/call/{tool_name}")
async def openai_call(slug: str, tool_name: str, request: Request):
    # Accepts OpenAI function call format, returns result
    ...

# Simple REST
@app.post("/rest/{slug}/tools/{tool_name}")
async def rest_call(slug: str, tool_name: str, request: Request):
    # Plain JSON in, plain JSON out
    ...
```

---

## 5. API Import Layer

### 5.1 OpenAPI Parser

```typescript
// lib/importers/openapi.ts
interface ParsedEndpoint {
  method: HttpMethod;
  path: string;
  summary: string;
  description: string;
  tags: string[];
  pathParams: Parameter[];
  queryParams: Parameter[];
  bodySchema: JSONSchema | null;
  responseSchema: JSONSchema | null;
}

async function parseOpenAPISpec(specUrl: string): Promise<ParsedEndpoint[]> {
  const spec = await fetchAndValidateSpec(specUrl);
  const endpoints: ParsedEndpoint[] = [];
  
  for (const [path, pathItem] of Object.entries(spec.paths)) {
    for (const method of HTTP_METHODS) {
      const operation = pathItem[method];
      if (!operation) continue;
      
      endpoints.push({
        method: method.toUpperCase() as HttpMethod,
        path,
        summary: operation.summary ?? '',
        description: operation.description ?? '',
        tags: operation.tags ?? [],
        pathParams: extractParams(operation, path, 'path'),
        queryParams: extractParams(operation, path, 'query'),
        bodySchema: extractBodySchema(operation),
        responseSchema: extractResponseSchema(operation),
      });
    }
  }
  
  return endpoints;
}
```

### 5.2 AI Endpoint Matcher

When a user describes a tool they want in natural language, the AI Endpoint Matcher finds the best-fit endpoint from the imported list:

```typescript
async function matchEndpointToDescription(
  description: string,
  endpoints: ParsedEndpoint[]
): Promise<{ endpoint: ParsedEndpoint; confidence: number; reasoning: string }> {
  const endpointSummaries = endpoints.map(e => 
    `${e.method} ${e.path} — ${e.summary}`
  ).join('\n');
  
  const response = await claude.messages.create({
    model: 'claude-opus-4-7',
    messages: [{
      role: 'user',
      content: `Given these API endpoints:\n${endpointSummaries}\n\n` +
               `Which endpoint best matches this description: "${description}"?\n` +
               `Reply with JSON: { "index": N, "confidence": 0-1, "reasoning": "..." }`
    }],
    max_tokens: 300,
  });
  
  // Parse and return
}
```

---

## 6. AI Integration

### 6.1 Tool Generation Prompt

```typescript
const TOOL_GENERATION_SYSTEM_PROMPT = `
You are an expert at creating MCP (Model Context Protocol) tool definitions
for AI agents. Given an API endpoint and a description of what the tool should do,
generate a precise tool configuration.

Rules:
- Tool names must be snake_case, verb-first (get_, create_, update_, list_, delete_, send_)
- Descriptions must be specific enough for an AI to know WHEN to use this tool
- Parameter descriptions must explain what values are acceptable
- Only include parameters that are actually useful to an AI agent
- Mark parameters as "forced" if they should always have a fixed value
`.trim();

async function generateToolFromDescription(
  userDescription: string,
  endpoint: ParsedEndpoint,
  productContext: string
): Promise<ToolConfiguration> {
  const response = await claude.messages.create({
    model: 'claude-opus-4-7',
    system: TOOL_GENERATION_SYSTEM_PROMPT,
    messages: [{
      role: 'user',
      content: buildToolGenerationPrompt(userDescription, endpoint, productContext)
    }],
    max_tokens: 1500,
  });
  
  return parseToolConfig(response.content[0].text);
}
```

### 6.2 Playground Implementation

The Playground sends each user message to Claude with the connector's tools registered as Claude tool-use definitions. Claude calls tools, Elliot's platform API proxies the calls to the Connector Runtime, and results come back through.

```typescript
// api/connectors/[id]/playground/route.ts
export async function POST(req: Request) {
  const { messages, connectorId } = await req.json();
  
  // Load connector's tools in Claude tool-use format
  const tools = await getConnectorToolsForClaude(connectorId);
  
  // System prompt: connector's system prompt + connector context
  const systemPrompt = await buildPlaygroundSystemPrompt(connectorId);
  
  const stream = claude.messages.stream({
    model: 'claude-opus-4-7',
    system: systemPrompt,
    messages,
    tools,
    max_tokens: 4096,
  });
  
  // When Claude calls a tool, proxy to Connector Runtime
  stream.on('tool_use', async (toolUse) => {
    const result = await callConnectorTool(connectorId, toolUse.name, toolUse.input);
    // Feed tool result back to Claude
  });
  
  return stream.toReadableStream();
}
```

---

## 7. Security Model

### 7.1 Threat Model

| Threat | Mitigation |
|---|---|
| Agent using another user's connector | Connector slugs are non-guessable UUIDs by default; API keys are scoped per connector |
| Product credentials leaked to agents | Credentials stored in Supabase Vault; never sent to agents; injected server-side |
| SSRF (agent tricks Elliot into calling internal URLs) | Validate product base_url against blocklist of private IP ranges and internal hostnames |
| SQL injection via tool parameters | All DB queries use parameterized statements; tool parameters never interpolated into SQL |
| Prompt injection via API responses | API responses are returned as structured JSON, not interpreted by Elliot's LLM |
| API key brute-forcing | bcrypt hashing with cost 12; rate limiting on auth failures |
| Excessive agent calls | Per-connector rate limiting; configurable by owner |

### 7.2 Secret Storage

```
Product credentials → Supabase Vault (AES-256 encryption)
  Referenced by secret_id in auth_config JSONB
  Retrieved only in the Connector Runtime, never in the web app

Connector API keys → bcrypt hash (cost 12) stored in api_keys.key_hash
  Full key shown once at creation, never stored in plaintext
  key_prefix stored for identification (e.g., "sk-ell-AbCd...")

JWT tokens (Supabase Auth) → httpOnly cookies, never localStorage
```

### 7.3 SSRF Protection

```python
import ipaddress

BLOCKED_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
]

def validate_base_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        return False
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(parsed.hostname))
        for blocked in BLOCKED_RANGES:
            if ip in blocked:
                return False
    except Exception:
        return False
    return True
```

---

## 8. Deployment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Vercel                               │
│  Next.js 15 (Platform UI + API Routes)                      │
│  Auto-scaling, edge CDN, serverless functions               │
└──────────────────────────┬──────────────────────────────────┘
                           │
       ┌───────────────────┼────────────────────┐
       │                   │                    │
┌──────▼──────┐   ┌────────▼───────┐   ┌───────▼───────┐
│  Supabase   │   │    Railway     │   │  Future:      │
│  PostgreSQL │   │ Connector      │   │  Redis cache  │
│  Auth       │   │ Runtime        │   │  (connector   │
│  Storage    │   │ (Docker)       │   │   config TTL) │
│  Vault      │   │ FastAPI        │   └───────────────┘
└─────────────┘   │ uvicorn        │
                  └────────────────┘
```

### Environment Variables

**Platform (Vercel):**
```env
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
ANTHROPIC_API_KEY=
CONNECTOR_RUNTIME_URL=https://runtime.elliot.ai
CONNECTOR_RUNTIME_SECRET=   # shared secret for platform→runtime calls
```

**Connector Runtime (Railway):**
```env
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
CONNECTOR_RUNTIME_SECRET=
MAX_RATE_LIMIT_PER_HOUR=1000
CACHE_TTL_SECONDS=60
LOG_LEVEL=info
PORT=8000
```

---

## 9. How Elliot Differs From cheap-MCP

Both projects expose MCP-compatible connectors, but they solve different problems.

| Dimension | cheap-MCP | Elliot |
|---|---|---|
| **Primary use case** | Query YOUR data (files, DBs) | Wrap YOUR product (APIs + actions) |
| **Operation types** | Read-only queries | Full CRUD + action endpoints |
| **Composition** | Single-source tools | Multi-step Skills across tools |
| **Import model** | Upload a CSV or connect a DB | Import an OpenAPI spec or Postman collection |
| **AI assistance** | Generate filter config | Generate tool from description + match endpoint |
| **Testing** | Test with sample parameters | Full playground with real Claude agent |
| **Target user** | Data analyst / developer | Product team / integration engineer |
| **Output** | Data rows and aggregations | Product capabilities as agent actions |
| **System prompts** | Not supported | First-class Prompt concept |
| **Multi-product** | One server per user | One connector per product (user can have many) |

---

## 10. Future Architecture Considerations

### Caching Layer (Phase 2)
Replace in-memory connector config cache with Redis for multi-instance consistency:
```
Connector Runtime instance 1 ──┐
Connector Runtime instance 2 ──┼──→ Redis (connector config cache, TTL 60s)
Connector Runtime instance 3 ──┘        ↑ invalidated on connector deploy
```

### AI-Orchestrated Skills (Phase 2)
For `ai_orchestrated` mode, the runtime makes a planning call to Claude with the available tools and the skill's goal, then executes the plan:
```
Agent calls skill "onboard_customer"
  → Runtime sends planning prompt to Claude:
      "Goal: onboard a new customer. Available tools: [...]"
  → Claude generates plan: [step1, step2, step3]
  → Runtime executes plan
  → Returns consolidated result
```

### Connector Marketplace (Phase 3)
Allow users to publish their connectors as reusable templates that others can import and configure for their own product instance — similar to Zapier's integration templates.

### Webhook Triggers (Phase 3)
Allow product events to trigger agent workflows:
```
User's product → webhook → Elliot Runtime → trigger Skill execution → agent completes workflow
```
