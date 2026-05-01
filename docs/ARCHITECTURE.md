# Elliot — Complete System Architecture

---

## 1. Full System Diagram

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                              ELLIOT — FULL SYSTEM MAP                                ║
╠══════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                      ║
║  ┌──────────────────────────────────────────────────────────────────────────────┐   ║
║  │                       PHASE 1 — LOCAL / SINGLE USER                          │   ║
║  │                                                                              │   ║
║  │  ╔══════════════════════╗  stdio/JSON-RPC  ╔══════════════════════════════╗  │   ║
║  │  ║   Claude Code        ║◄───────────────►║  @elliot/mcp-plugin          ║  │   ║
║  │  ║   GitHub Copilot     ║                 ║  (MCP Server, stdio)         ║  │   ║
║  │  ║                      ║                 ║                              ║  │   ║
║  │  ║  Agentic Q&A flow:   ║                 ║  Tools the agent calls:      ║  │   ║
║  │  ║  "What APIs do you   ║                 ║  • elliot_discover_source    ║  │   ║
║  │  ║   have?"             ║                 ║  • elliot_query_sql          ║  │   ║
║  │  ║  "What business      ║                 ║  • elliot_profile_column     ║  │   ║
║  │  ║   tools to expose?"  ║                 ║  • elliot_create_tool        ║  │   ║
║  │  ║  "Let me fetch the   ║                 ║  • elliot_preview_tool       ║  │   ║
║  │  ║   API and build..."  ║                 ║  • elliot_build_connector    ║  │   ║
║  │  ╚══════════════════════╝                 ║  • elliot_start_runtime      ║  │   ║
║  │                                           ╚══════════════╦═══════════════╝  │   ║
║  │                                                          ║                   │   ║
║  │                                           ╔══════════════▼═══════════════╗  │   ║
║  │                                           ║      @elliot/core            ║  │   ║
║  │                                           ║                              ║  │   ║
║  │  ┌──────────────────────────────────────┐ ║  ┌──────────────────────┐   ║  │   ║
║  │  │   User's Existing Product            │ ║  │  Source Fetcher      │   ║  │   ║
║  │  │                                      │ ║  │  • REST (undici)     │   ║  │   ║
║  │  │  ┌────────────┐  ┌────────────────┐  │◄╫─►│  • Files (CSV/JSON) │   ║  │   ║
║  │  │  │ REST APIs  │  │  SQLite / PG   │  │ ║  │  • DB (better-sql3) │   ║  │   ║
║  │  │  │ /customers │  │  local DB      │  │ ║  │  • Pagination auto  │   ║  │   ║
║  │  │  │ /orders    │  │                │  │ ║  └──────────┬───────────┘   ║  │   ║
║  │  │  │ /products  │  └────────────────┘  │ ║             │               ║  │   ║
║  │  │  └────────────┘                      │ ║  ┌──────────▼───────────┐   ║  │   ║
║  │  │  ┌────────────────────────────────┐  │ ║  │  SQLite Engine       │   ║  │   ║
║  │  │  │ Files: orders.csv, schema.json │  │ ║  │  • JSON flattener    │   ║  │   ║
║  │  │  └────────────────────────────────┘  │ ║  │  • Type inferrer     │   ║  │   ║
║  │  └──────────────────────────────────────┘ ║  │  • In-memory tables  │   ║  │   ║
║  │                                           ║  │  • Parameterized SQL │   ║  │   ║
║  │                                           ║  └──────────┬───────────┘   ║  │   ║
║  │                                           ║             │               ║  │   ║
║  │                                           ║  ┌──────────▼───────────┐   ║  │   ║
║  │                                           ║  │  Tool Registry       │   ║  │   ║
║  │                                           ║  │  • ToolDefinition[]  │   ║  │   ║
║  │                                           ║  │  • SkillDefinition[] │   ║  │   ║
║  │                                           ║  │  • ConnectorConfig   │   ║  │   ║
║  │                                           ║  │  • .elliot/ persist  │   ║  │   ║
║  │                                           ║  └──────────────────────┘   ║  │   ║
║  │                                           ╚══════════════╦═══════════════╝  │   ║
║  │                                                          ║                   │   ║
║  │  ┌───────────────────────────────────────────────────────▼─────────────┐   │   ║
║  │  │           @elliot/connector-runtime   (local MCP server)            │   │   ║
║  │  │                                                                     │   │   ║
║  │  │   $ elliot serve --port 3001                                        │   │   ║
║  │  │   MCP endpoint: http://localhost:3001/mcp                           │   │   ║
║  │  │   OpenAI endpoint: http://localhost:3001/openai                     │   │   ║
║  │  │                                                                     │   │   ║
║  │  │   ┌────────────────────┐      ┌────────────────────┐               │   │   ║
║  │  │   │  Claude Desktop    │      │  Any MCP Client    │               │   │   ║
║  │  │   │  (MCP config)      │──────│  / Custom Agent    │──────────►    │   │   ║
║  │  │   └────────────────────┘      └────────────────────┘               │   │   ║
║  │  └─────────────────────────────────────────────────────────────────────┘   │   ║
║  │                                                                              │   ║
║  │  ┌──────────────────────────────────────────────────────────────────────┐   │   ║
║  │  │  @elliot/studio   React + Vite + shadcn/ui   http://localhost:5173   │   │   ║
║  │  │                                                                      │   │   ║
║  │  │  ┌───────────────┐ ┌───────────────┐ ┌─────────────┐ ┌───────────┐  │   │   ║
║  │  │  │  Connector    │ │  Tool Builder │ │  Metrics &  │ │  Eval     │  │   │   ║
║  │  │  │  Manager      │ │  (visual)     │ │  Analytics  │ │  Framework│  │   │   ║
║  │  │  └───────────────┘ └───────────────┘ └─────────────┘ └───────────┘  │   │   ║
║  │  └──────────────────────────────────────────────────────────────────────┘   │   ║
║  └──────────────────────────────────────────────────────────────────────────────┘   ║
║                                                                                      ║
║  ┌──────────────────────────────────────────────────────────────────────────────┐   ║
║  │                 PHASE 2 — EVALUATION & DEEP MONITORING                       │   ║
║  │                                                                              │   ║
║  │  Golden Test Suites ─► Run Agent Against Connector ─► Score Tool Selection  │   ║
║  │  Session Recording  ─► Replay & Inspect            ─► Detect Regressions    │   ║
║  │  Description Quality Analyzer  ─►  Connector Quality Score (0-100)          │   ║
║  └──────────────────────────────────────────────────────────────────────────────┘   ║
║                                                                                      ║
║  ┌──────────────────────────────────────────────────────────────────────────────┐   ║
║  │                    PHASE 3 — CLOUD HOSTING (FUTURE)                          │   ║
║  │                                                                              │   ║
║  │  ┌──────────────────────────────────────────────────────────────────────┐   │   ║
║  │  │  Cloud Connector Runtime                                              │   │   ║
║  │  │  https://runtime.elliot.ai/c/{slug}                                   │   │   ║
║  │  │  Multi-user  │  Team Metrics  │  Connector Marketplace               │   │   ║
║  │  └──────────────────────────────────────────────────────────────────────┘   │   ║
║  └──────────────────────────────────────────────────────────────────────────────┘   ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
```

---

## 2. Monorepo Structure

```
elliot/
├── package.json                    # pnpm workspace root
├── pnpm-workspace.yaml
├── tsconfig.base.json              # shared TS config (strict, ES2022, bundler)
├── vitest.workspace.ts             # vitest workspace pointing to all packages
├── .eslintrc.cjs                   # shared ESLint config
├── .prettierrc
│
├── packages/
│   │
│   ├── core/                       # @elliot/core
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── vitest.config.ts
│   │   └── src/
│   │       ├── index.ts
│   │       ├── sources/
│   │       │   ├── types.ts           # SourceConfig, ApiEndpoint, AuthConfig
│   │       │   ├── api-fetcher.ts     # undici-based REST fetcher
│   │       │   ├── file-reader.ts     # CSV (papaparse) + JSON/JSONL
│   │       │   ├── db-connector.ts    # better-sqlite3 / pg direct queries
│   │       │   ├── paginator.ts       # cursor / offset / page / link-header
│   │       │   └── schema-detector.ts # infer schema from sample JSON
│   │       ├── sqlite/
│   │       │   ├── engine.ts          # SQLiteEngine: load, query, refresh
│   │       │   ├── flattener.ts       # nested JSON → flat rows + related tables
│   │       │   ├── type-inferrer.ts   # detect INTEGER/REAL/TEXT from values
│   │       │   └── query-runner.ts    # safe parameterized query execution
│   │       ├── tools/
│   │       │   ├── types.ts           # ToolDefinition, SkillDefinition, ConnectorConfig
│   │       │   ├── registry.ts        # ToolRegistry: add, get, list, validate
│   │       │   ├── validator.ts       # zod schemas for all tool config
│   │       │   └── executor.ts        # execute a ToolDefinition with parameters
│   │       ├── connector/
│   │       │   ├── builder.ts         # ConnectorBuilder: assemble ConnectorConfig
│   │       │   ├── serializer.ts      # read/write .connector.json
│   │       │   └── schema-gen.ts      # ToolDefinition → MCP JSON Schema
│   │       └── workspace/
│   │           └── index.ts           # read/write .elliot/ workspace dir
│   │
│   ├── mcp-plugin/                 # @elliot/mcp-plugin
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── vitest.config.ts
│   │   └── src/
│   │       ├── index.ts               # entry: start McpServer with StdioTransport
│   │       ├── server.ts              # register all tools on McpServer
│   │       ├── session.ts             # ElliotSession: holds all in-flight state
│   │       └── tools/
│   │           ├── source-tools.ts    # discover, list, preview, remove source
│   │           ├── sql-tools.ts       # query_sql, get_schema, sample_data, profile_column
│   │           ├── tool-tools.ts      # create, update, list, preview, delete tool
│   │           ├── skill-tools.ts     # create, list, preview skill
│   │           ├── connector-tools.ts # build, export, start_runtime, get_config
│   │           └── context-tools.ts   # set_product_context, get_session_state
│   │
│   ├── connector-runtime/          # @elliot/connector-runtime
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── vitest.config.ts
│   │   └── src/
│   │       ├── index.ts               # CLI entry: `elliot serve`
│   │       ├── server.ts              # MCP server for a deployed connector
│   │       ├── loader.ts              # load + validate .connector.json
│   │       ├── executor.ts            # execute tool calls, refresh data, run SQL
│   │       ├── cache.ts               # TTL cache for fetched source data
│   │       ├── audit.ts               # append-only log to .elliot/audit.ndjson
│   │       └── protocols/
│   │           ├── mcp.ts             # JSON-RPC 2.0 / MCP handler
│   │           └── openai.ts          # OpenAI function-calling format
│   │
│   └── studio/                     # @elliot/studio
│       ├── package.json
│       ├── vite.config.ts
│       ├── tsconfig.json
│       ├── tsconfig.node.json
│       ├── components.json            # shadcn/ui config
│       ├── vitest.config.ts
│       ├── index.html
│       └── src/
│           ├── main.tsx
│           ├── App.tsx
│           ├── router.tsx             # React Router v6
│           ├── lib/
│           │   ├── utils.ts           # cn() + helpers
│           │   ├── api.ts             # fetch wrapper for connector-runtime REST API
│           │   └── store.ts           # Zustand global state
│           ├── pages/
│           │   ├── Dashboard.tsx
│           │   ├── SourcesPage.tsx
│           │   ├── ToolsPage.tsx
│           │   ├── SkillsPage.tsx
│           │   ├── ConnectorPage.tsx
│           │   ├── PlaygroundPage.tsx
│           │   ├── MetricsPage.tsx
│           │   └── EvaluationPage.tsx
│           ├── components/
│           │   ├── ui/                # generated shadcn/ui components
│           │   ├── layout/            # Sidebar, Header, AppShell
│           │   ├── sources/
│           │   ├── tools/
│           │   ├── playground/
│           │   ├── metrics/
│           │   └── evaluation/
│           └── tests/
│               ├── unit/
│               └── integration/
│
└── docs/
    ├── ARCHITECTURE.md
    ├── DEVELOPMENT_GUIDE.md
    ├── CORE_CONCEPTS.md
    ├── PRODUCT_SPECIFICATION.md
    └── DEVELOPMENT_MISSIONS.md
```

---

## 3. Core Data Models

All types live in `packages/core/src/tools/types.ts` and `packages/core/src/sources/types.ts`.

### 3.1 Source Types

```typescript
export type AuthType = 'none' | 'api_key' | 'bearer' | 'basic' | 'custom_header';
export type SourceType = 'api' | 'file' | 'database';
export type RefreshStrategy = 'on_call' | 'cache_5m' | 'cache_1h' | 'cache_1d' | 'manual';
export type PaginationType = 'cursor' | 'offset' | 'page' | 'link_header' | 'none';

export interface SourceConfig {
  id: string;
  name: string;
  type: SourceType;
  refreshStrategy: RefreshStrategy;

  // --- API sources ---
  baseUrl?: string;
  endpoints?: ApiEndpointConfig[];
  auth?: AuthConfig;
  defaultHeaders?: Record<string, string>;
  timeoutMs?: number;          // default 30_000

  // --- File sources ---
  filePath?: string;           // absolute or relative to .elliot/
  fileType?: 'csv' | 'json' | 'jsonl';
  csvOptions?: { delimiter?: string; hasHeader?: boolean; encoding?: BufferEncoding };

  // --- Database sources ---
  connectionString?: string;   // stored encrypted in workspace
  dbType?: 'sqlite' | 'postgresql';
  queries?: DbQueryConfig[];   // named queries to run and load as tables
}

export interface ApiEndpointConfig {
  id: string;
  path: string;                // e.g. "/v1/customers"
  method: 'GET' | 'POST';
  description: string;
  headers?: Record<string, string>;
  queryParams?: Record<string, string>;  // static params always sent
  bodyTemplate?: Record<string, unknown>;
  pagination?: PaginationConfig;
  dataPath?: string;           // JSONPath to array in response e.g. "data.items"
  tableName: string;           // target SQLite table name
}

export interface AuthConfig {
  type: AuthType;
  apiKeyHeader?: string;       // e.g. "X-API-Key"
  apiKeyValue?: string;        // stored encrypted
  bearerToken?: string;        // stored encrypted
  username?: string;
  password?: string;           // stored encrypted
  customHeaders?: Record<string, string>;
}

export interface PaginationConfig {
  type: PaginationType;
  pageSize: number;
  maxPages?: number;           // safety limit, default 100
  // cursor
  cursorResponsePath?: string; // JSONPath to next cursor, e.g. "meta.next_cursor"
  cursorParam?: string;        // query param name, e.g. "cursor"
  // offset / page
  offsetParam?: string;
  limitParam?: string;
  pageParam?: string;
  totalPath?: string;          // JSONPath to total count (for offset mode)
}

export interface DbQueryConfig {
  id: string;
  name: string;                // human-readable
  sql: string;                 // SELECT query to run
  tableName: string;           // target SQLite table name
  parameters?: Record<string, unknown>;
}
```

### 3.2 Tool & Connector Types

```typescript
export type ParameterType = 'string' | 'number' | 'integer' | 'boolean' | 'date' | 'array';
export type ToolCategory = 'READ' | 'ACTION' | 'AGGREGATE';

export interface ToolDefinition {
  id: string;
  name: string;                // snake_case, verb-first: get_, list_, create_, update_, search_
  description: string;         // rich — the AI reads this to decide when and how to call this tool
  category: ToolCategory;

  sources: ToolSourceRef[];    // which sources to refresh before executing
  sql: string;                 // parameterized SQL query on in-memory SQLite tables
                               // uses :param_name syntax for parameters

  parameters: ParameterDefinition[];
  responseShape?: ResponseShape;

  // For ACTION tools: the outbound API call to make after SQL validation
  action?: ActionDefinition;

  // Override source-level refresh for this tool
  refreshStrategy?: RefreshStrategy;

  metadata: {
    createdAt: string;
    updatedAt: string;
    executionCount: number;
    lastExecutedAt?: string;
    averageLatencyMs?: number;
  };
}

export interface ToolSourceRef {
  sourceId: string;
  tableNames: string[];        // which tables from this source this tool uses
  refreshOnCall: boolean;      // re-fetch before executing (overrides refreshStrategy)
}

export interface ParameterDefinition {
  name: string;
  type: ParameterType;
  description: string;         // explain acceptable values to the AI
  required: boolean;
  defaultValue?: unknown;
  enumValues?: (string | number)[];
  pattern?: string;            // regex for string validation
  minimum?: number;
  maximum?: number;
  itemType?: ParameterType;   // for array type: element type
}

export interface ResponseShape {
  includeFields?: string[];    // if set, only these fields are returned
  renameFields?: Record<string, string>;
  maxRows?: number;            // default 1000
  includeMetadata?: boolean;   // append { _rowCount, _truncated, _latencyMs }
}

export interface ActionDefinition {
  sourceId: string;
  endpointId: string;          // must point to POST/PUT/PATCH/DELETE endpoint
  parameterMapping: Record<string, string>; // tool_param → body/path field
  rollbackSql?: string;        // SQL to detect if action already done (idempotency)
}

export interface SkillDefinition {
  id: string;
  name: string;
  description: string;
  inputParameters: ParameterDefinition[];
  steps: SkillStep[];
  metadata: { createdAt: string; updatedAt: string };
}

export interface SkillStep {
  id: string;
  toolId: string;
  outputAlias: string;         // referenced in subsequent steps as {{steps.ALIAS.field}}
  inputBindings: Record<string, string>;
  // binding values:
  //   "{{skill.input.customer_id}}"  — from skill's input params
  //   "{{steps.customer.id}}"        — from a previous step's output field
  //   "active"                       — literal value
}

export interface PromptDefinition {
  id: string;
  name: string;
  type: 'system' | 'template' | 'few_shot';
  content: string;
  variables?: string[];        // {{variable}} names extracted from content
  metadata: { createdAt: string; updatedAt: string };
}

export interface ConnectorConfig {
  id: string;
  name: string;
  slug: string;
  description: string;
  version: string;             // semver

  product: ProductContext;
  sources: SourceConfig[];
  tools: ToolDefinition[];
  skills: SkillDefinition[];
  prompts: PromptDefinition[];

  runtime: {
    port: number;              // default 3001
    rateLimit?: { requestsPerMinute: number };
    cors?: { allowedOrigins: string[] };
  };

  metadata: {
    createdAt: string;
    updatedAt: string;
    elliotVersion: string;
  };
}

export interface ProductContext {
  name: string;
  description: string;
  domain: string;              // e.g. "e-commerce", "crm", "analytics"
  version?: string;
  docsUrl?: string;
}
```

### 3.3 SQLite Engine Types

```typescript
export interface FlattenResult {
  primaryTable: FlattenedTable;
  relatedTables: FlattenedTable[];   // from nested arrays of objects
}

export interface FlattenedTable {
  name: string;
  columns: ColumnMeta[];
  rows: Record<string, SqliteValue>[];
  rowCount: number;
  sourceRef: string;
  fetchedAt: Date;
  warnings: FlattenWarning[];
}

export interface ColumnMeta {
  name: string;                // SQL-safe column name
  originalPath: string;        // original JSON path: "address.city"
  sqliteType: 'INTEGER' | 'REAL' | 'TEXT' | 'BLOB';
  nullable: boolean;
  inferredFormat?: 'iso_date' | 'email' | 'url' | 'uuid' | 'enum' | 'boolean_string' | 'json_array';
  cardinality?: number;        // distinct value count (filled by profile)
  nullCount?: number;
  sampleValues?: unknown[];    // up to 5 examples
}

export type FlattenWarning =
  | { type: 'truncated_array'; field: string; originalLength: number; keptLength: number }
  | { type: 'circular_ref'; path: string }
  | { type: 'mixed_types'; field: string; types: string[] }
  | { type: 'reserved_keyword'; original: string; renamed: string }
  | { type: 'name_collision'; path1: string; path2: string; resolved: string }
  | { type: 'deep_nesting'; path: string; depth: number; serialized: true }
  | { type: 'large_response'; rows: number; memoryEstimateMb: number };

export type SqliteValue = string | number | bigint | null | Buffer;
```

### 3.4 Audit & Evaluation Types

```typescript
export interface AuditLogEntry {
  id: string;
  connectorId: string;
  sessionId: string;
  timestamp: string;           // ISO 8601
  protocol: 'mcp' | 'openai' | 'rest';
  method: 'tools/list' | 'tools/call' | 'skills/call' | 'initialize';
  toolName?: string;
  skillName?: string;
  parameters?: Record<string, unknown>;
  responseRowCount?: number;
  latencyMs: number;
  success: boolean;
  errorCode?: string;
  errorMessage?: string;
  cacheHit?: boolean;
  sourcesFetched?: string[];
}

export interface EvalSuite {
  id: string;
  connectorId: string;
  name: string;
  description?: string;
  cases: EvalCase[];
  createdAt: string;
}

export interface EvalCase {
  id: string;
  question: string;            // natural language user question
  context?: string;            // additional context to inject
  expectedToolCalls: ExpectedCall[];
  expectedFinalAnswer?: string; // for LLM-judge scoring (optional)
  tags?: string[];
}

export interface ExpectedCall {
  toolName: string;
  required: boolean;           // if false, this is "nice to have" (partial credit)
  requiredParameters?: Record<string, unknown>;  // parameters that MUST be present
  forbiddenParameters?: string[];                // parameters that must NOT be present
}

export interface EvalRunResult {
  id: string;
  suiteId: string;
  connectorVersion: string;
  runAt: string;
  overallScore: number;        // 0–100
  toolSelectionScore: number;  // 0–100: did agent pick the right tools?
  parameterScore: number;      // 0–100: did agent use correct params?
  completionScore: number;     // 0–100: did agent complete the task?
  caseResults: CaseRunResult[];
  regressions: string[];       // case IDs that regressed vs previous run
}

export interface CaseRunResult {
  caseId: string;
  passed: boolean;
  score: number;               // 0–100
  actualCalls: Array<{ toolName: string; parameters: Record<string, unknown>; success: boolean }>;
  toolSelectionMatch: boolean;
  parameterMatch: boolean;
  missingTools: string[];
  unexpectedTools: string[];
  notes: string;
}
```

---

## 4. SQLite Engine Design

The SQLite engine is the heart of Elliot. After fetching any data source (API, file, or database), the engine flattens the response into an in-memory SQLite database and allows SQL queries on top of it.

### 4.1 JSON Flattening Algorithm

The flattener handles any arbitrary JSON shape:

```
Input: [
  {
    "id": 1,
    "name": "Alice",
    "address": { "city": "NYC", "zip": "10001" },
    "tags": ["vip", "enterprise"],
    "orders": [
      { "id": "ord_1", "total": 99.0, "items": [{ "sku": "A", "qty": 2 }] },
      { "id": "ord_2", "total": 45.0, "items": [{ "sku": "B", "qty": 1 }] }
    ]
  }
]

Output tables:
  customers:            id=1, name="Alice", address_city="NYC", address_zip="10001",
                        tags='["vip","enterprise"]'   ← array of primitives → JSON string
  customers_orders:     _parent_id=1, id="ord_1", total=99.0
                        _parent_id=1, id="ord_2", total=45.0
  customers_orders_items: _parent_id="ord_1", sku="A", qty=2
                           _parent_id="ord_2", sku="B", qty=1
```

**Nesting rules:**
- Primitive values → column in parent table
- Object values → flattened with `_` separator (`address.city` → `address_city`)
- Array of primitives → serialized to `TEXT` as JSON string
- Array of objects → new table with `_parent_id` foreign key
- Nesting depth > 5 → serialize entire subtree as `TEXT` (with warning)
- Circular references → detected with `WeakSet`, replaced with `"[circular]"` (with warning)

### 4.2 Type Inference

```typescript
function inferType(samples: unknown[]): ColumnMeta['sqliteType'] {
  const nonNull = samples.filter(v => v !== null && v !== undefined);
  if (nonNull.every(v => Number.isInteger(v)))   return 'INTEGER';
  if (nonNull.every(v => typeof v === 'number'))  return 'REAL';
  if (nonNull.every(v => typeof v === 'boolean')) return 'INTEGER';  // 0/1
  return 'TEXT';  // everything else (dates, IDs, mixed) → TEXT
}

// Additional format detection on TEXT columns:
function inferFormat(samples: string[]): ColumnMeta['inferredFormat'] | undefined {
  const isoDateRe = /^\d{4}-\d{2}-\d{2}(T[\d:.Z+-]+)?$/;
  const uuidRe = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  if (samples.every(s => isoDateRe.test(s))) return 'iso_date';
  if (samples.every(s => uuidRe.test(s)))    return 'uuid';
  if (samples.every(s => emailRe.test(s)))   return 'email';
  if (samples.every(s => s === 'true' || s === 'false')) return 'boolean_string';
  return undefined;
}
```

### 4.3 Safe Query Execution

All SQL is executed with `better-sqlite3`'s parameterized API. User-provided SQL strings (from tool definitions) are **never string-interpolated** — parameters are always bound:

```typescript
export function runToolQuery(
  db: Database,
  sql: string,
  params: Record<string, unknown>
): Row[] {
  // Validate: no DDL, no multiple statements, no subquery injection vectors
  validateToolSql(sql);

  // better-sqlite3 named parameters
  const stmt = db.prepare(sql);
  const result = stmt.all(params);   // params bound safely: { :customer_id: "..." }

  return result as Row[];
}

function validateToolSql(sql: string): void {
  const normalized = sql.trim().toLowerCase();
  const forbidden = ['drop ', 'create ', 'alter ', 'insert ', 'update ', 'delete ',
                     'attach ', 'detach ', 'pragma ', '--', ';'];
  for (const f of forbidden) {
    if (normalized.includes(f)) {
      throw new ElliotError('INVALID_SQL', `Tool SQL contains forbidden keyword: ${f}`);
    }
  }
  // Must start with SELECT
  if (!normalized.startsWith('select')) {
    throw new ElliotError('INVALID_SQL', 'Tool SQL must be a SELECT statement');
  }
}
```

### 4.4 Column Name Safety

```typescript
const SQL_RESERVED = new Set(['order', 'select', 'from', 'where', 'group', 'having',
  'limit', 'offset', 'join', 'on', 'as', 'and', 'or', 'not', 'in', 'is', 'null',
  'like', 'between', 'exists', 'case', 'when', 'then', 'else', 'end', 'index',
  'table', 'create', 'drop', 'insert', 'update', 'delete', 'column', 'default']);

function safeName(path: string, existingNames: Set<string>): string {
  // 1. Replace non-alphanumeric with underscore
  let name = path.replace(/[^a-zA-Z0-9]/g, '_').replace(/^_+|_+$/g, '').toLowerCase();

  // 2. Prefix reserved keywords
  if (SQL_RESERVED.has(name) || /^\d/.test(name)) name = `_${name}`;

  // 3. Resolve collisions by appending _2, _3, etc.
  if (existingNames.has(name)) {
    let n = 2;
    while (existingNames.has(`${name}_${n}`)) n++;
    name = `${name}_${n}`;
  }

  existingNames.add(name);
  return name;
}
```

---

## 5. MCP Plugin Tool Catalog

The MCP plugin exposes these tools to Claude Code / GitHub Copilot. Each tool is defined with a Zod schema.

### 5.1 Source Management

| Tool | Description | Key Parameters |
|---|---|---|
| `elliot_discover_source` | Fetch a data source, infer schema, load into SQLite | `type`, `name`, `baseUrl`/`filePath`/`connectionString`, `auth`, `endpoints[]` |
| `elliot_list_sources` | List all registered sources with table names and row counts | — |
| `elliot_preview_source` | Return first N rows from a source's table | `sourceId`, `tableName`, `limit` |
| `elliot_profile_source` | Deep profile: cardinality, nulls, min/max, format per column | `sourceId`, `tableName` |
| `elliot_refresh_source` | Re-fetch a source and reload tables | `sourceId` |
| `elliot_remove_source` | Remove a source and its tables from SQLite | `sourceId` |

### 5.2 SQL Exploration

| Tool | Description | Key Parameters |
|---|---|---|
| `elliot_get_schema` | Return all table names + column definitions in SQLite | `tableName?` (filter to one table) |
| `elliot_query_sql` | Execute a SELECT on in-memory SQLite | `sql`, `params?` |
| `elliot_sample_data` | Return random N rows from a table | `tableName`, `n` |
| `elliot_profile_column` | Stats for one column: distinct, null%, min, max, top-5 values | `tableName`, `columnName` |
| `elliot_explain_query` | EXPLAIN QUERY PLAN for a SQL statement | `sql` |

### 5.3 Tool Building

| Tool | Description | Key Parameters |
|---|---|---|
| `elliot_create_tool` | Create a tool definition | `name`, `description`, `category`, `sources[]`, `sql`, `parameters[]`, `responseShape?` |
| `elliot_update_tool` | Update an existing tool | `toolId`, `...fields` |
| `elliot_list_tools` | List all tools with metadata | — |
| `elliot_get_tool` | Get full tool definition | `toolId` |
| `elliot_delete_tool` | Remove a tool | `toolId` |
| `elliot_preview_tool` | Execute a tool with test parameters against live data | `toolId`, `parameters` |
| `elliot_validate_sql` | Validate a SQL string without executing it | `sql` |

### 5.4 Skill Building

| Tool | Description | Key Parameters |
|---|---|---|
| `elliot_create_skill` | Create a multi-step skill | `name`, `description`, `inputParameters[]`, `steps[]` |
| `elliot_list_skills` | List all skills | — |
| `elliot_preview_skill` | Execute a skill with test inputs | `skillId`, `inputs` |
| `elliot_delete_skill` | Remove a skill | `skillId` |

### 5.5 Connector Management

| Tool | Description | Key Parameters |
|---|---|---|
| `elliot_set_product_context` | Set product name, description, domain | `name`, `description`, `domain` |
| `elliot_build_connector` | Package all tools+skills+prompts into a connector | `name`, `toolIds[]`, `skillIds[]`, `promptIds?[]`, `port?` |
| `elliot_get_connector` | Get current connector config | — |
| `elliot_export_connector` | Write `.connector.json` to disk | `outputPath` |
| `elliot_start_runtime` | Start the connector as a local MCP server | `port?` |
| `elliot_stop_runtime` | Stop the local MCP server | — |
| `elliot_get_connection_config` | Return Claude Desktop / Cursor config snippet | `client: 'claude' \| 'cursor' \| 'openai'` |
| `elliot_get_session_state` | Return full current session state | — |

### 5.6 Tool Definitions (TypeScript)

```typescript
// Example tool definition using @modelcontextprotocol/sdk
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';

server.tool(
  'elliot_create_tool',
  {
    name: z.string().regex(/^[a-z][a-z0-9_]*$/).describe('Snake_case tool name, verb-first'),
    description: z.string().min(20).describe('Rich description for AI to understand when to use this'),
    category: z.enum(['READ', 'ACTION', 'AGGREGATE']),
    sources: z.array(z.object({
      sourceId: z.string(),
      tableNames: z.array(z.string()),
      refreshOnCall: z.boolean().default(false),
    })),
    sql: z.string().startsWith('SELECT').describe('Parameterized SELECT query using :param_name syntax'),
    parameters: z.array(z.object({
      name: z.string(),
      type: z.enum(['string', 'number', 'integer', 'boolean', 'date', 'array']),
      description: z.string(),
      required: z.boolean(),
      defaultValue: z.unknown().optional(),
      enumValues: z.array(z.union([z.string(), z.number()])).optional(),
    })),
    responseShape: z.object({
      includeFields: z.array(z.string()).optional(),
      maxRows: z.number().int().positive().max(10_000).default(1_000),
    }).optional(),
  },
  async ({ name, description, category, sources, sql, parameters, responseShape }, session) => {
    // Validate SQL
    validateToolSql(sql);

    // Validate parameters are referenced in SQL
    validateParameterUsage(sql, parameters);

    const tool: ToolDefinition = {
      id: generateId(),
      name, description, category, sources, sql, parameters,
      responseShape: responseShape ?? { maxRows: 1000 },
      metadata: { createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
                  executionCount: 0 },
    };

    session.toolRegistry.add(tool);
    await session.workspace.save();

    return {
      content: [{ type: 'text', text: `✓ Tool "${name}" created. ${parameters.length} parameters. Use elliot_preview_tool to test it.` }],
    };
  }
);
```

---

## 6. Connector Runtime Protocol

The connector runtime (`elliot serve`) reads a `.connector.json` and starts an MCP server.

### 6.1 Tool Call Lifecycle

```
Agent sends:  POST /mcp  (or stdio)
              { "jsonrpc": "2.0", "method": "tools/call",
                "params": { "name": "get_customers", "arguments": { "status": "active" } } }

  1. VALIDATE
     └─ Zod parse arguments against tool.parameters schema
     └─ If invalid → return error: { code: -32602, message: "Invalid params: ..." }

  2. REFRESH DATA (if needed)
     └─ For each tool.sources where refreshOnCall=true OR cache expired:
        └─ Re-fetch source endpoint(s) → flatten → reload SQLite table(s)
        └─ Strategy: on_call → always; cache_5m → if >5 min since last fetch; etc.

  3. EXECUTE SQL
     └─ db.prepare(tool.sql).all({ status: "active" })
     └─ Apply responseShape (field filter, max rows)

  4. EXECUTE ACTION (ACTION tools only)
     └─ Build HTTP request from parameterMapping
     └─ Inject product auth credentials
     └─ Execute outbound call
     └─ Return combined result

  5. AUDIT LOG
     └─ Append to .elliot/audit.ndjson (async, non-blocking)

  6. RETURN
     └─ { "jsonrpc": "2.0", "result": {
            "content": [{ "type": "text", "text": "[{...}]" }],
            "_meta": { "rowCount": 5, "latencyMs": 142, "cacheHit": false }
          } }
```

### 6.2 Skill Execution (Sequential)

```typescript
async function executeSkill(
  skill: SkillDefinition,
  inputs: Record<string, unknown>,
  context: RuntimeContext,
): Promise<unknown> {
  const stepOutputs: Record<string, unknown> = {};

  for (const step of skill.steps) {
    const tool = context.registry.get(step.toolId);

    // Resolve bindings: {{skill.input.X}} or {{steps.ALIAS.field.path}}
    const resolvedArgs = resolveBindings(step.inputBindings, { skillInput: inputs, stepOutputs });

    // Execute tool (goes through full tool lifecycle above)
    const result = await executeTool(tool, resolvedArgs, context);

    stepOutputs[step.outputAlias] = result;
  }

  return stepOutputs;
}

function resolveBindings(
  bindings: Record<string, string>,
  ctx: { skillInput: Record<string, unknown>; stepOutputs: Record<string, unknown> },
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(bindings).map(([param, template]) => {
      if (typeof template !== 'string') return [param, template];

      const skillMatch = template.match(/^\{\{skill\.input\.(.+)\}\}$/);
      if (skillMatch) return [param, get(ctx.skillInput, skillMatch[1])];

      const stepMatch = template.match(/^\{\{steps\.(\w+)\.(.+)\}\}$/);
      if (stepMatch) return [param, get(ctx.stepOutputs[stepMatch[1]], stepMatch[2])];

      return [param, template]; // literal value
    }),
  );
}
```

---

## 7. Evaluation Framework

### 7.1 Purpose

The evaluation framework answers the question: **"How well does an AI agent understand my connector?"**

It measures:
1. **Tool Selection Accuracy** — when asked a question, does the agent pick the right tool?
2. **Parameter Accuracy** — does the agent fill in the correct parameters?
3. **Task Completion** — does the agent successfully complete multi-step workflows?
4. **Description Quality** — automated analysis of tool descriptions for clarity and completeness

### 7.2 Evaluation Flow

```
User defines EvalSuite:
  cases: [
    { question: "How many active customers do we have?",
      expectedToolCalls: [{ toolName: "get_customer_count", requiredParameters: { status: "active" } }] },
    { question: "Get all orders over $500 from last week",
      expectedToolCalls: [{ toolName: "list_orders", requiredParameters: { min_total: 500 } }] },
  ]

Run evaluation:
  For each case:
    1. Send question to Claude with connector tools loaded
    2. Record all tool calls Claude makes (name + parameters)
    3. Score against expectedToolCalls:
       - toolSelectionScore: did Claude call each required tool? (0/1 per tool)
       - parameterScore: for required tools, did all requiredParameters match? (0/1 per param)
    4. Optionally: LLM judge compares final answer to expectedFinalAnswer (0–1 score)

Overall score = (toolSelectionScore * 0.4) + (parameterScore * 0.4) + (completionScore * 0.2)
```

### 7.3 Description Quality Analyzer

Automated analysis run against each tool description:

```typescript
const QUALITY_CHECKS: QualityCheck[] = [
  { id: 'min_length', check: d => d.length >= 30, message: 'Description too short (< 30 chars)' },
  { id: 'starts_with_verb', check: d => /^(Get|List|Find|Create|Update|Delete|Search|Count|Calculate|Fetch|Return)/i.test(d), message: 'Description should start with a verb' },
  { id: 'mentions_return', check: d => /returns?|gives?|provides?|fetches?/i.test(d), message: 'Description should mention what is returned' },
  { id: 'no_jargon', check: d => !/endpoint|api|sql|query|database/i.test(d), message: 'Avoid technical jargon (endpoint, SQL, API) — write for the AI, not the developer' },
  { id: 'parameter_descriptions', check: (_, params) => params.every(p => p.description.length >= 10), message: 'All parameters need descriptions of at least 10 characters' },
  { id: 'enum_documented', check: (_, params) => params.filter(p => p.enumValues?.length).every(p => p.description.includes(p.enumValues![0].toString())), message: 'Parameters with enum values should list valid values in description' },
];
```

---

## 8. Edge Cases Catalog

### 8.1 JSON Flattening Edge Cases

| Case | Behavior |
|---|---|
| Array of primitives: `tags: ["a","b"]` | Serialized to `TEXT` as JSON string |
| Array of objects: `orders: [{...}]` | New related table `{parent}_orders` with `_parent_id` FK |
| Nesting depth > 5 levels | Entire subtree serialized to `TEXT` + warning |
| Circular reference: `obj.self = obj` | Detected via `WeakSet`, replaced with `"[circular]"` + warning |
| Mixed column types: sometimes `string`, sometimes `number` | Column typed as `TEXT`; values coerced to string |
| Column name = SQL keyword: `order`, `from` | Prefixed: `_order`, `_from` + warning |
| Two paths produce same column name | Second renamed with `_2` suffix + warning |
| Unicode/emoji in key names: `"résumé"` | Normalized to ASCII; values preserved |
| Empty object: `{}` | Row inserted with all NULLs |
| Empty array: `[]` | Related table created but no rows inserted |
| Array > 1000 items | Truncated to 1000 + warning with original count |
| `null` value | `NULL` in SQLite |
| `true`/`false` booleans | Stored as `INTEGER` `1`/`0` |
| Numbers > `Number.MAX_SAFE_INTEGER` | Stored as `TEXT` to preserve precision |
| Very large strings (> 64KB) | Stored but column flagged; no truncation |

### 8.2 API Fetching Edge Cases

| Case | Behavior |
|---|---|
| `429 Too Many Requests` | Read `Retry-After` header; exponential backoff up to 3 retries |
| `401 Unauthorized` | Surface clear error; prompt user to check auth config |
| `5xx Server Error` | Retry twice with 1s backoff; surface error after 3 failures |
| SSL certificate error | Clear error with guidance; dev mode can skip verify |
| Redirect loop | Follow up to 10 redirects; fail with error after |
| Response > 50MB | Stream in chunks of 5MB; warn about memory usage |
| Non-JSON response (HTML, XML) | Check `Content-Type`; if HTML, likely auth redirect — say so clearly |
| `{ data: [...] }` wrapper | Auto-detect and unwrap common response envelopes |
| API key visible in error logs | Redact auth headers from all log output |
| DNS resolution failure | Clear error with `nslookup` suggestion |
| Connection timeout | Default 30s; configurable per source; clear timeout error |
| Infinite pagination (cursor never null) | Hard limit of 100 pages; warn user |
| Pagination schema drift across pages | Detect new columns on page 2+; add as nullable |

### 8.3 Tool Execution Edge Cases

| Case | Behavior |
|---|---|
| SQL returns empty result set | Return `[]` (not null, not error) |
| `SUM(column)` on empty set | Returns `NULL` in SQLite → convert to `0` |
| Agent sends wrong type (string for integer) | Coerce if safe (e.g., `"42"` → `42`); reject if not |
| Agent omits required parameter | Return descriptive error listing the missing param and its description |
| SQL runs longer than 5 seconds | Interrupt + error: "Query exceeded 5s limit. Simplify the SQL or add a LIMIT clause." |
| `maxRows` exceeded in result | Truncate + add `_meta: { truncated: true, totalRows: N }` to response |
| Tool references source that no longer exists | Error: source deleted after tool was created; prompt to re-discover |
| Cache hit but source has been updated | No way to know automatically; configurable `refreshStrategy` is the answer |
| Parallel tool calls (agent calls 3 tools at once) | SQLite is in-process; reads are safe; writes serialized via queue |
| SQL references table that failed to load | Clear error naming which source failed and why |

### 8.4 MCP Protocol Edge Cases

| Case | Behavior |
|---|---|
| Client sends malformed JSON | Return `{ error: { code: -32700, message: "Parse error" } }` |
| Client sends unknown method | Return `{ error: { code: -32601, message: "Method not found" } }` |
| Client sends `id: null` (notification) | Process request but don't send response |
| `tools/call` with unknown tool name | Return `{ error: { code: -32602, message: "Unknown tool: X" } }` |
| `initialize` called twice | Respond normally (idempotent) |
| Client disconnects mid-call (stdio) | Detect EOF; clean up session state |
| Tool name collision between tools and skills | Skills exposed as tools with skill_ prefix if overlap |

### 8.5 Skill Execution Edge Cases

| Case | Behavior |
|---|---|
| Step references undefined `outputAlias` | Validate at skill creation time; build-time error |
| Step 2 references `{{steps.step1.nonexistent}}` | Returns `undefined` for that parameter; downstream tool receives null |
| Step tool fails (API down, SQL error) | Skill aborts; return partial results with error detail per step |
| Binding type mismatch (string where integer expected) | Coerce; fail fast with clear error if impossible |
| Circular skill (skill A calls tool that calls skill B calls skill A) | Skills can't call other skills (Phase 1); depth limit applied in Phase 2 |
| Step reuses same outputAlias | Overwrite; last step with that alias wins (warn user) |

---

## 9. Security Model

### 9.1 Credential Storage

Credentials (API keys, bearer tokens, passwords) are stored in `.elliot/secrets.enc` — AES-256-GCM encrypted with a key derived from a workspace password or OS keychain. They are **never**:
- Written to `.connector.json` in plaintext
- Logged in any audit log
- Sent to Claude Code as tool responses

When the connector runtime needs credentials, it reads from `.elliot/secrets.enc` directly and injects them into HTTP requests server-side.

### 9.2 SQL Injection Prevention

Tool SQL strings are:
1. Validated at creation time (must start with `SELECT`, no DDL keywords, single statement)
2. Executed using `better-sqlite3`'s named parameter binding — never string-formatted
3. Run inside a read-only SQLite transaction

The SQLite database is in-memory and contains only data the user explicitly loaded — there is no persistent schema to attack.

### 9.3 SSRF Prevention

Before fetching any user-provided URL:
```typescript
function validateUrl(url: string): void {
  const parsed = new URL(url);
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new ElliotError('INVALID_URL', 'Only http/https URLs allowed');
  }
  // Resolve hostname and block private ranges
  const resolved = dns.lookup(parsed.hostname);
  if (isPrivateIp(resolved)) {
    throw new ElliotError('SSRF_BLOCKED', 'Connections to private IP ranges are not allowed');
  }
}
```

### 9.4 Rate Limiting (Connector Runtime)

The connector runtime applies per-session rate limiting to prevent runaway agent loops:
```typescript
const limiter = new RateLimiter({ requestsPerMinute: 60 });  // configurable in ConnectorConfig
```

---

## 10. Testing Strategy

### 10.1 Unit Tests (`vitest`)

Every module in `@elliot/core` has a co-located unit test covering:
- Flattener: 15+ test cases covering all edge cases (circular refs, mixed types, deep nesting, etc.)
- Type inferrer: all SQLite type and format inference paths
- Column name safety: all reserved keyword and collision scenarios
- SQL validator: all forbidden keyword patterns
- Parameter resolver (skill bindings): all template patterns

Example:
```typescript
// packages/core/tests/unit/flattener.test.ts
import { describe, it, expect } from 'vitest';
import { flattenJson } from '../../src/sqlite/flattener';

describe('flattenJson', () => {
  it('flattens nested objects with underscore separator', () => {
    const rows = flattenJson([{ user: { name: 'Alice', age: 30 } }], 'test');
    expect(rows.primaryTable.columns.map(c => c.name)).toContain('user_name');
    expect(rows.primaryTable.columns.map(c => c.name)).toContain('user_age');
  });

  it('extracts arrays of objects as related tables', () => {
    const rows = flattenJson([{ id: 1, orders: [{ id: 'o1' }] }], 'customers');
    expect(rows.relatedTables).toHaveLength(1);
    expect(rows.relatedTables[0].name).toBe('customers_orders');
    expect(rows.relatedTables[0].rows[0]._parent_id).toBe(1);
  });

  it('serializes arrays of primitives to JSON string', () => {
    const rows = flattenJson([{ tags: ['a', 'b'] }], 'test');
    expect(rows.primaryTable.rows[0].tags).toBe('["a","b"]');
  });

  it('detects and breaks circular references', () => {
    const obj: Record<string, unknown> = { id: 1 };
    obj.self = obj;
    const rows = flattenJson([obj], 'test');
    expect(rows.primaryTable.warnings.some(w => w.type === 'circular_ref')).toBe(true);
  });

  it('truncates large arrays and emits warning', () => {
    const data = [{ id: 1, items: Array.from({ length: 2000 }, (_, i) => ({ n: i })) }];
    const rows = flattenJson(data, 'test');
    expect(rows.relatedTables[0].rowCount).toBe(1000);
    expect(rows.primaryTable.warnings.some(w => w.type === 'truncated_array')).toBe(true);
  });

  it('renames reserved SQL keywords', () => {
    const rows = flattenJson([{ order: 'abc', from: 'xyz' }], 'test');
    const colNames = rows.primaryTable.columns.map(c => c.name);
    expect(colNames).toContain('_order');
    expect(colNames).toContain('_from');
  });
});
```

### 10.2 Integration Tests

Integration tests spin up real (mock) HTTP servers:

```typescript
// packages/core/tests/integration/api-fetcher.test.ts
import { createServer } from 'http';
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { ApiFetcher } from '../../src/sources/api-fetcher';

describe('ApiFetcher integration', () => {
  let server: ReturnType<typeof createServer>;
  let port: number;

  beforeAll(() => {
    server = createServer((req, res) => {
      if (req.url === '/api/customers') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify([{ id: 1, name: 'Alice' }, { id: 2, name: 'Bob' }]));
      } else if (req.url?.startsWith('/api/paginated')) {
        const page = new URL(req.url, 'http://x').searchParams.get('page') ?? '1';
        const isLast = page === '2';
        res.end(JSON.stringify({ data: [{ id: +page }], next_page: isLast ? null : 2 }));
      }
    });
    port = await listenRandomPort(server);
  });

  afterAll(() => server.close());

  it('fetches and returns JSON array', async () => {
    const fetcher = new ApiFetcher({ baseUrl: `http://localhost:${port}` });
    const result = await fetcher.fetch({ path: '/api/customers', method: 'GET', tableName: 'customers' });
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe('Alice');
  });

  it('auto-paginates using page parameter', async () => {
    const result = await fetcher.fetch({
      path: '/api/paginated', method: 'GET', tableName: 'items',
      pagination: { type: 'page', pageParam: 'page', pageSize: 1, dataPath: 'data',
                    totalPath: 'total' },
    });
    expect(result).toHaveLength(2);
  });
});
```

### 10.3 MCP Protocol Tests

```typescript
// packages/mcp-plugin/tests/integration/mcp-server.test.ts
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { describe, it, expect, beforeEach } from 'vitest';
import { createElliotServer } from '../../src/server';

describe('Elliot MCP server', () => {
  let client: Client;

  beforeEach(async () => {
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    const server = createElliotServer();
    await server.connect(serverTransport);
    client = new Client({ name: 'test', version: '1.0' });
    await client.connect(clientTransport);
  });

  it('lists all elliot tools', async () => {
    const { tools } = await client.listTools();
    const names = tools.map(t => t.name);
    expect(names).toContain('elliot_discover_source');
    expect(names).toContain('elliot_create_tool');
    expect(names).toContain('elliot_build_connector');
  });

  it('discovers a source and returns schema', async () => {
    const result = await client.callTool({
      name: 'elliot_discover_source',
      arguments: {
        type: 'file',
        name: 'test_source',
        filePath: './fixtures/customers.csv',
        fileType: 'csv',
      },
    });
    expect(result.content[0].text).toContain('customers');
  });
});
```

---

## 11. Phase Roadmap

| Phase | Scope | Key Deliverables |
|---|---|---|
| **1** | Local, single-user, Claude Code plugin | MCP plugin + core engine + connector runtime + basic Studio |
| **2** | Evaluation & monitoring | Eval framework, session recording, metrics dashboard, description quality analyzer |
| **3** | Cloud hosting | Hosted connector URL, multi-user auth, team workspaces, connector marketplace |
| **4** | Enterprise | SSO, audit compliance, SLA, private cloud deployment |

Phase 1 has **no authentication** — it's a local developer tool. Multi-user auth is deferred to Phase 3.
