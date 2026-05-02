# Elliot — Development Guide

Complete guide to setting up the monorepo, building each package, running tests, and walking through Phase 1 development.

---

## 1. Prerequisites

| Tool | Version | Install |
|---|---|---|
| Node.js | 20 LTS + | https://nodejs.org |
| pnpm | 9+ | `npm i -g pnpm` |
| Git | any | — |

Verify:
```bash
node --version   # v20.x.x
pnpm --version   # 9.x.x
```

---

## 2. Monorepo Setup

### 2.1 Initialize the workspace

```bash
git clone https://github.com/elibarak12/elliot.git
cd elliot

# Install all dependencies across all packages
pnpm install
```

### 2.2 Root configuration files

**`package.json`** (workspace root):
```json
{
  "name": "elliot",
  "private": true,
  "scripts": {
    "dev": "concurrently -n plugin,studio -c cyan,magenta \"pnpm --filter @elliot/mcp-plugin run dev\" \"pnpm --filter @elliot/studio run dev\"",
    "setup": "node packages/mcp-plugin/scripts/install.mjs",
    "build": "pnpm -r run build",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:coverage": "vitest run --coverage",
    "lint": "eslint packages/*/src --ext .ts,.tsx",
    "typecheck": "pnpm -r run typecheck",
    "clean": "pnpm -r run clean"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "@typescript-eslint/eslint-plugin": "^7.0.0",
    "@typescript-eslint/parser": "^7.0.0",
    "concurrently": "^8.2.0",
    "eslint": "^9.0.0",
    "prettier": "^3.0.0",
    "typescript": "^5.4.0",
    "vitest": "^1.5.0",
    "@vitest/coverage-v8": "^1.5.0"
  }
}
```

**`pnpm-workspace.yaml`**:
```yaml
packages:
  - 'packages/*'
```

**`tsconfig.base.json`**:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "lib": ["ES2022"],
    "strict": true,
    "exactOptionalPropertyTypes": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "verbatimModuleSyntax": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "skipLibCheck": true
  }
}
```

**`vitest.workspace.ts`**:
```typescript
import { defineWorkspace } from 'vitest/config';

export default defineWorkspace([
  'packages/core/vitest.config.ts',
  'packages/mcp-plugin/vitest.config.ts',
  'packages/connector-runtime/vitest.config.ts',
  'packages/studio/vitest.config.ts',
]);
```

---

## 3. Package: `@elliot/core`

The shared library. All business logic lives here — source fetching, SQLite engine, tool registry, connector serializer.

### 3.1 Setup

```
packages/core/
├── package.json
├── tsconfig.json
├── vitest.config.ts
└── src/
    ├── index.ts         # re-exports all public APIs
    ├── sources/
    ├── sqlite/
    ├── tools/
    ├── connector/
    └── workspace/
```

**`packages/core/package.json`**:
```json
{
  "name": "@elliot/core",
  "version": "0.1.0",
  "type": "module",
  "exports": {
    ".": { "import": "./dist/index.js", "types": "./dist/index.d.ts" }
  },
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "typecheck": "tsc --noEmit",
    "clean": "rm -rf dist",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "better-sqlite3": "^9.4.0",
    "undici": "^6.0.0",
    "papaparse": "^5.4.0",
    "zod": "^3.22.0",
    "jsonpath-plus": "^9.0.0"
  },
  "devDependencies": {
    "@types/better-sqlite3": "^7.6.0",
    "@types/papaparse": "^5.3.0",
    "typescript": "^5.4.0",
    "vitest": "^1.5.0"
  }
}
```

**`packages/core/tsconfig.json`**:
```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "outDir": "./dist",
    "rootDir": "./src"
  },
  "include": ["src/**/*"]
}
```

**`packages/core/vitest.config.ts`**:
```typescript
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    include: ['src/**/*.test.ts', 'tests/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      include: ['src/**'],
      exclude: ['src/**/*.test.ts'],
      thresholds: { lines: 85, functions: 85, branches: 80 },
    },
  },
});
```

### 3.2 Key Implementation Notes

**`src/sqlite/engine.ts`** — The central SQLite engine:
```typescript
import Database from 'better-sqlite3';
import type { FlattenedTable, FlattenResult } from './types.js';

export class SQLiteEngine {
  private db: Database.Database;
  private loadedTables: Map<string, FlattenedTable> = new Map();

  constructor() {
    this.db = new Database(':memory:');
    this.db.pragma('journal_mode = WAL');
    this.db.pragma('foreign_keys = ON');
  }

  loadTable(result: FlattenResult): void {
    this.createTable(result.primaryTable);
    for (const related of result.relatedTables) {
      this.createTable(related);
    }
  }

  private createTable(table: FlattenedTable): void {
    const cols = table.columns
      .map(c => `"${c.name}" ${c.sqliteType}${c.nullable ? '' : ' NOT NULL'}`)
      .join(', ');
    this.db.exec(`DROP TABLE IF EXISTS "${table.name}"`);
    this.db.exec(`CREATE TABLE "${table.name}" (${cols})`);

    const insert = this.db.prepare(
      `INSERT INTO "${table.name}" VALUES (${table.columns.map(() => '?').join(', ')})`
    );
    const insertMany = this.db.transaction((rows: Record<string, unknown>[]) => {
      for (const row of rows) {
        insert.run(table.columns.map(c => row[c.name] ?? null));
      }
    });
    insertMany(table.rows);
    this.loadedTables.set(table.name, table);
  }

  query(sql: string, params: Record<string, unknown> = {}): Record<string, unknown>[] {
    const stmt = this.db.prepare(sql);
    return stmt.all(params) as Record<string, unknown>[];
  }

  getTableNames(): string[] {
    return this.db.prepare("SELECT name FROM sqlite_master WHERE type='table'")
      .all().map((r: Record<string, unknown>) => r['name'] as string);
  }

  getTableSchema(tableName: string): { name: string; type: string; notnull: number }[] {
    return this.db.pragma(`table_info("${tableName}")`) as { name: string; type: string; notnull: number }[];
  }

  close(): void {
    this.db.close();
  }
}
```

### 3.3 Build & Test

```bash
# From root
pnpm --filter @elliot/core run build
pnpm --filter @elliot/core run test

# Watch mode during development
pnpm --filter @elliot/core run test:watch
```

---

## 4. Package: `@elliot/mcp-plugin`

The MCP server that users install into Claude Code or Codex. Communicates over HTTP (StreamableHTTP). Runs persistently on port 3000. All Claude Code sessions and Studio connect to the same server instance, sharing a single in-memory SQLite engine and tool registry.

### 4.1 Setup

```
packages/mcp-plugin/
├── package.json
├── tsconfig.json
├── vitest.config.ts
├── scripts/
│   └── install.mjs     # auto-registers with Claude Code + Codex
└── src/
    ├── index.ts        # HTTP server: Express + StreamableHTTPServerTransport on :3000
    ├── server.ts       # create McpServer + register all tools
    ├── session.ts      # ElliotSession singleton (shared across all HTTP sessions)
    └── tools/
        ├── source-tools.ts
        ├── sql-tools.ts
        ├── tool-tools.ts
        ├── skill-tools.ts
        ├── connector-tools.ts
        ├── context-tools.ts
        └── studio-tools.ts  # meta-tools, only visible to elliot-studio client
```

**`packages/mcp-plugin/package.json`**:
```json
{
  "name": "@elliot/mcp-plugin",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "build": "tsc",
    "typecheck": "tsc --noEmit",
    "clean": "rm -rf dist",
    "test": "vitest run",
    "setup": "node scripts/install.mjs"
  },
  "dependencies": {
    "@elliot/core": "workspace:*",
    "@modelcontextprotocol/sdk": "^1.10.0",
    "express": "^4.19.0",
    "zod": "^3.22.0"
  },
  "devDependencies": {
    "@types/express": "^4.17.0",
    "tsx": "^4.0.0",
    "typescript": "^5.4.0",
    "vitest": "^1.5.0"
  }
}
```

### 4.2 MCP Server Entry Point

**`src/index.ts`** — Express server with `StreamableHTTPServerTransport`. All HTTP sessions share one `ElliotSession` singleton so state (loaded tables, tool registry) persists across Claude Code reconnections.

```typescript
import express from 'express';
import { randomUUID } from 'crypto';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { createElliotServer } from './server.js';
import { ElliotSession } from './session.js';

const PORT = parseInt(process.env.ELLIOT_PORT ?? '3000', 10);
const app = express();
app.use(express.json());

// CORS — allow Studio dev server
app.use((_req, res, next) => {
  res.header('Access-Control-Allow-Origin', 'http://localhost:5173');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Mcp-Session-Id, x-client-name');
  res.header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  if (_req.method === 'OPTIONS') { res.sendStatus(204); return; }
  next();
});

// Shared singleton — all MCP sessions read/write the same state
const session = new ElliotSession();
await session.load();

// sessionId → transport routing table
const transports = new Map<string, StreamableHTTPServerTransport>();

app.all('/mcp', async (req, res) => {
  const sessionId = req.headers['mcp-session-id'] as string | undefined;

  if (sessionId && transports.has(sessionId)) {
    await transports.get(sessionId)!.handleRequest(req, res);
    return;
  }

  // New connection — create a transport + server pair
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: () => randomUUID(),
  });

  transport.onSessionId = (id) => transports.set(id, transport);
  transport.onClose = () => {
    const id = transport.sessionId;
    if (id) transports.delete(id);
  };

  const server = createElliotServer(session);
  await server.connect(transport);
  await transport.handleRequest(req, res);
});

const httpServer = app.listen(PORT, () => {
  console.log(`✓ Elliot plugin  → http://localhost:${PORT}/mcp`);
  console.log(`  Studio         → http://localhost:5173`);
});

process.on('SIGINT', async () => {
  await session.save();
  httpServer.close();
  process.exit(0);
});
```

### 4.3 Session State

**`src/session.ts`**:
```typescript
import { SQLiteEngine, ToolRegistry, ConnectorBuilder, WorkspaceStore } from '@elliot/core';
import type { ProductContext, SourceConfig } from '@elliot/core';

export class ElliotSession {
  readonly sqliteEngine: SQLiteEngine;
  readonly toolRegistry: ToolRegistry;
  readonly connectorBuilder: ConnectorBuilder;
  readonly workspace: WorkspaceStore;

  productContext?: ProductContext;
  sources: Map<string, SourceConfig> = new Map();
  runtimeProcess?: import('child_process').ChildProcess;

  constructor() {
    this.sqliteEngine = new SQLiteEngine();
    this.toolRegistry = new ToolRegistry();
    this.connectorBuilder = new ConnectorBuilder();
    this.workspace = new WorkspaceStore(process.cwd());
  }

  async load(): Promise<void> {
    const saved = await this.workspace.loadSession();
    if (saved) {
      this.productContext = saved.productContext;
      for (const source of saved.sources) {
        this.sources.set(source.id, source);
      }
      for (const tool of saved.tools) {
        this.toolRegistry.add(tool);
      }
    }
  }

  async save(): Promise<void> {
    await this.workspace.saveSession({
      productContext: this.productContext,
      sources: [...this.sources.values()],
      tools: this.toolRegistry.getAll(),
      skills: this.toolRegistry.getAllSkills(),
    });
  }
}
```

### 4.4 Auto-Register With Claude Code & Codex

Run once after cloning. Writes project-level config files that are auto-discovered when the folder is opened, and also registers at user scope via each tool's CLI.

**`scripts/install.mjs`**:
```javascript
#!/usr/bin/env node
/**
 * Registers Elliot with Claude Code and Codex — no manual config editing needed.
 *
 * 1. Writes .mcp.json at project root      → Claude Code auto-discovers on folder open
 * 2. Runs `claude mcp add-json`            → also registers at user scope (if CLI present)
 * 3. Writes .codex/config.toml            → Codex auto-discovers on folder open
 * 4. Writes ~/.codex/config.toml          → also registers at Codex user scope
 */
import { execSync } from 'child_process';
import { writeFileSync, mkdirSync, existsSync, readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import os from 'os';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(__dirname, '..', '..', '..');
const PLUGIN_URL = 'http://localhost:3000/mcp';

// ── 1. Claude Code — project-level .mcp.json ─────────────────────────────────
const mcpJsonPath = resolve(PROJECT_ROOT, '.mcp.json');
const mcpConfig = existsSync(mcpJsonPath)
  ? JSON.parse(readFileSync(mcpJsonPath, 'utf-8'))
  : { mcpServers: {} };
mcpConfig.mcpServers ??= {};
mcpConfig.mcpServers.elliot = { type: 'http', url: PLUGIN_URL };
writeFileSync(mcpJsonPath, JSON.stringify(mcpConfig, null, 2));
console.log('✓ .mcp.json written — Claude Code auto-loads on folder open');

// ── 2. Claude Code — user scope via CLI ──────────────────────────────────────
try {
  execSync(
    `claude mcp add-json elliot '{"type":"http","url":"${PLUGIN_URL}"}' --scope user`,
    { stdio: 'pipe' }
  );
  console.log('✓ Claude Code: registered at user scope (all projects)');
} catch {
  console.log('  claude CLI not found — project .mcp.json is sufficient');
}

// ── 3. Codex — project-level .codex/config.toml ──────────────────────────────
const codexDir = resolve(PROJECT_ROOT, '.codex');
mkdirSync(codexDir, { recursive: true });
const elliotToml = `\n[mcp_servers.elliot]\nurl = "${PLUGIN_URL}"\n`;
const codexProjectPath = resolve(codexDir, 'config.toml');
const projectToml = existsSync(codexProjectPath) ? readFileSync(codexProjectPath, 'utf-8') : '';
if (!projectToml.includes('[mcp_servers.elliot]')) {
  writeFileSync(codexProjectPath, projectToml + elliotToml);
}
console.log('✓ .codex/config.toml written — Codex auto-loads on folder open');

// ── 4. Codex — user scope via ~/.codex/config.toml ───────────────────────────
try {
  const userCodexDir = resolve(os.homedir(), '.codex');
  mkdirSync(userCodexDir, { recursive: true });
  const userCodexPath = resolve(userCodexDir, 'config.toml');
  const existing = existsSync(userCodexPath) ? readFileSync(userCodexPath, 'utf-8') : '';
  if (!existing.includes('[mcp_servers.elliot]')) {
    writeFileSync(userCodexPath, existing + elliotToml);
    console.log('✓ Codex: registered at user scope (~/.codex/config.toml)');
  } else {
    console.log('  Codex user config already has elliot — skipped');
  }
} catch {
  console.log('  Could not write ~/.codex/config.toml — project-level is sufficient');
}

console.log('\nAll done. Now run:');
console.log('  pnpm dev    →  plugin :3000  |  Studio :5173');
```

Run it:
```bash
pnpm install
pnpm setup      # writes configs + registers with Claude Code & Codex
pnpm dev        # starts plugin :3000 + Studio :5173
```

### 4.5 Test The Plugin

```bash
pnpm --filter @elliot/mcp-plugin run test
```

Key integration test uses `InMemoryTransport` from the MCP SDK to test the server without HTTP:
```typescript
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { createElliotServer } from '../../src/server.js';
import { ElliotSession } from '../../src/session.js';

const session = new ElliotSession();
const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
const server = createElliotServer(session);
await server.connect(serverTransport);

const client = new Client({ name: 'test', version: '0.0.1' });
await client.connect(clientTransport);

const { tools } = await client.listTools();
// assert expected tools are present...
```

---

## 5. Package: `@elliot/connector-runtime`

The deployable MCP server. Takes a `.connector.json` and exposes it as a standalone MCP endpoint that other agents can connect to.

### 5.1 Setup

**`packages/connector-runtime/package.json`**:
```json
{
  "name": "@elliot/connector-runtime",
  "version": "0.1.0",
  "type": "module",
  "bin": { "elliot": "./dist/index.js" },
  "scripts": {
    "build": "tsc && chmod +x dist/index.js",
    "typecheck": "tsc --noEmit",
    "clean": "rm -rf dist",
    "test": "vitest run"
  },
  "dependencies": {
    "@elliot/core": "workspace:*",
    "@modelcontextprotocol/sdk": "^1.10.0",
    "express": "^4.19.0",
    "zod": "^3.22.0"
  }
}
```

### 5.2 CLI Entry

**`src/index.ts`**:
```typescript
#!/usr/bin/env node
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { parseArgs } from 'util';
import { startConnectorServer } from './server.js';
import type { ConnectorConfig } from '@elliot/core';

const { values } = parseArgs({
  options: {
    port: { type: 'string', default: '3001' },
    connector: { type: 'string', default: '.elliot/connector.json' },
  },
});

const connectorPath = resolve(process.cwd(), values.connector!);
const config: ConnectorConfig = JSON.parse(readFileSync(connectorPath, 'utf-8'));
const port = parseInt(values.port!, 10);

await startConnectorServer(config, { port });

console.log(`\n✓ Elliot connector runtime started`);
console.log(`  Connector: ${config.name} v${config.version}`);
console.log(`  MCP endpoint: http://localhost:${port}/mcp`);
console.log(`  Tools: ${config.tools.length} | Skills: ${config.skills.length}`);
console.log(`\n  Add to your agent config:`);
console.log(`  { "${config.slug}": { "type": "http", "url": "http://localhost:${port}/mcp" } }`);
```

### 5.3 Usage

```bash
# Build
pnpm --filter @elliot/connector-runtime run build

# Serve a connector
node packages/connector-runtime/dist/index.js \
  --connector .elliot/connector.json \
  --port 3001
```

---

## 6. Package: `@elliot/studio`

The React dashboard. Uses **Vite** (not Next.js), **shadcn/ui**, **Tailwind CSS v4**, and **React Router v6**. Connects to the MCP plugin via `StreamableHTTPClientTransport` — no REST API.

### 6.1 Initial Setup

```bash
# If starting from scratch
cd packages/studio
npm create vite@latest . -- --template react-ts

# Install dependencies
pnpm add react-router-dom zustand @tanstack/react-query @modelcontextprotocol/sdk
pnpm add -D tailwindcss @tailwindcss/vite

# Add shadcn/ui
pnpm dlx shadcn@latest init
# ✓ Choose: TypeScript, Default style, Slate base, src/components/ui, CSS variables
```

### 6.2 Vite Config

Studio communicates with the plugin exclusively via MCP over HTTP — no proxy needed.

**`packages/studio/vite.config.ts`**:
```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
  },
});
```

### 6.3 Components.json (shadcn)

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "default",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "",
    "css": "src/index.css",
    "baseColor": "slate",
    "cssVariables": true
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

### 6.4 Adding shadcn Components

```bash
# From studio package root
pnpm dlx shadcn@latest add button card input textarea select badge
pnpm dlx shadcn@latest add dialog sheet tabs table
pnpm dlx shadcn@latest add toast sonner
pnpm dlx shadcn@latest add chart         # recharts wrapper
pnpm dlx shadcn@latest add code-block    # for SQL display
```

### 6.5 App Router

**`src/router.tsx`**:
```tsx
import { createBrowserRouter } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { Dashboard } from '@/pages/Dashboard';
import { SourcesPage } from '@/pages/SourcesPage';
import { ToolsPage } from '@/pages/ToolsPage';
import { SkillsPage } from '@/pages/SkillsPage';
import { ConnectorPage } from '@/pages/ConnectorPage';
import { PlaygroundPage } from '@/pages/PlaygroundPage';
import { MetricsPage } from '@/pages/MetricsPage';
import { EvaluationPage } from '@/pages/EvaluationPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'sources', element: <SourcesPage /> },
      { path: 'tools', element: <ToolsPage /> },
      { path: 'skills', element: <SkillsPage /> },
      { path: 'connector', element: <ConnectorPage /> },
      { path: 'playground', element: <PlaygroundPage /> },
      { path: 'metrics', element: <MetricsPage /> },
      { path: 'evaluation', element: <EvaluationPage /> },
    ],
  },
]);
```

**`src/main.tsx`**:
```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import './index.css';
import { router } from './router';

const queryClient = new QueryClient();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>
);
```

### 6.6 MCP Client

All Studio↔plugin communication goes through `StreamableHTTPClientTransport`. This is the only network layer — there is no REST API.

**`src/lib/mcp-client.ts`**:
```typescript
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const PLUGIN_URL = new URL('http://localhost:3000/mcp');
const SESSION_KEY = 'elliot-mcp-session-id';

let mcpClient: Client | null = null;

export async function getMcpClient(): Promise<Client> {
  if (mcpClient) return mcpClient;

  // Restore previous session ID across page reloads (workaround for SDK issue #852)
  const storedSessionId = sessionStorage.getItem(SESSION_KEY) ?? undefined;

  const transport = new StreamableHTTPClientTransport(PLUGIN_URL, {
    sessionId: storedSessionId,
    requestInit: {
      headers: { 'x-client-name': 'elliot-studio' },
    },
  });

  mcpClient = new Client({ name: 'elliot-studio', version: '0.1.0' });
  await mcpClient.connect(transport);

  const sessionId = transport.sessionId;
  if (sessionId) sessionStorage.setItem(SESSION_KEY, sessionId);

  return mcpClient;
}

export async function callTool(name: string, args: Record<string, unknown>) {
  const client = await getMcpClient();
  return client.callTool({ name, arguments: args });
}

export async function listTools() {
  const client = await getMcpClient();
  return client.listTools();
}
```

Use with React Query:
```typescript
// src/hooks/useTools.ts
import { useQuery, useMutation } from '@tanstack/react-query';
import { listTools, callTool } from '@/lib/mcp-client';

export function useTools() {
  return useQuery({ queryKey: ['tools'], queryFn: listTools });
}

export function useCallTool() {
  return useMutation({
    mutationFn: ({ name, args }: { name: string; args: Record<string, unknown> }) =>
      callTool(name, args),
  });
}
```

### 6.7 Zustand Store

**`src/lib/store.ts`**:
```typescript
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ConnectorConfig, ToolDefinition, SourceConfig } from '@elliot/core';

interface ElliotStore {
  connector: ConnectorConfig | null;
  sources: SourceConfig[];
  tools: ToolDefinition[];
  selectedToolId: string | null;

  setConnector: (c: ConnectorConfig) => void;
  selectTool: (id: string | null) => void;
}

export const useElliotStore = create<ElliotStore>()(
  persist(
    (set) => ({
      connector: null,
      sources: [],
      tools: [],
      selectedToolId: null,

      setConnector: (connector) => set({ connector, sources: connector.sources, tools: connector.tools }),
      selectTool: (id) => set({ selectedToolId: id }),
    }),
    { name: 'elliot-studio', partialize: (s) => ({ connector: s.connector }) }
  )
);
```

> **Important**: Every import from `@elliot/core` in Studio **must** use `import type { ... }`. Never import runtime values (`SQLiteEngine`, `ApiClient`, etc.) — those depend on Node.js native modules and will break the Vite browser build.

### 6.8 Run Studio

```bash
pnpm --filter @elliot/studio run dev
# Opens at http://localhost:5173
```

Or start everything at once from the repo root:
```bash
pnpm dev   # plugin :3000 + Studio :5173
```

---

## 7. Running All Tests

```bash
# All packages
pnpm test

# Single package
pnpm --filter @elliot/core test
pnpm --filter @elliot/mcp-plugin test

# With coverage
pnpm test:coverage

# Watch mode
pnpm test:watch
```

Coverage thresholds are enforced in each `vitest.config.ts`:
- Lines: 85%
- Functions: 85%
- Branches: 80%

CI will fail if these are not met.

---

## 8. Phase 1 Development Walkthrough

This section walks through how to actually BUILD a connector from scratch using the MCP plugin.

### Step 1: Setup

```bash
git clone https://github.com/elibarak12/elliot.git
cd elliot
pnpm install
pnpm setup      # writes .mcp.json + .codex/config.toml, registers with Claude Code & Codex
pnpm dev        # starts plugin on :3000 and Studio on :5173
```

Then open the project folder in Claude Code or Codex — Elliot is already registered via the project-level `.mcp.json` / `.codex/config.toml`. No manual config editing needed.

### Step 2: Open a project directory

Create or navigate to a folder for your connector work:
```bash
mkdir ~/my-connector && cd ~/my-connector
```

### Step 3: Start an Elliot session in Claude Code

Open Claude Code in your terminal and start a conversation:

```
You: I want to build a connector for my product using Elliot.

Claude: I'll help you build a connector step by step. Let me start
        by setting up context for your product.

        What is your product called, and what domain does it operate in?
        (e.g., e-commerce, CRM, analytics, HR, finance, etc.)
```

### Step 4: Claude discovers your sources

Claude will call `elliot_discover_source` for each API or file you provide:

```
You: It's called ShopOS — an e-commerce backend.
     API base URL is https://api.shopOS.internal/v2
     Auth: X-API-Key header with value "sk-test-abc123"
     Endpoints I want to use:
       GET /customers (returns array with pagination, cursor-based)
       GET /orders?customer_id=X
       GET /products?category=X

Claude: [calls elliot_discover_source for each endpoint]

        ✓ Loaded 3 sources into SQLite:
        - customers: 247 rows, columns: id, name, email, status, total_spent, created_at
        - orders: 1,842 rows, columns: id, customer_id, total, status, created_at
        - products: 56 rows, columns: id, name, sku, price, inventory_count, category

        What business tools do you want to expose?
        For example: "get customer order history", "find low-stock products", "calculate daily revenue"
```

### Step 5: Claude builds your tools

```
You: I want:
     1. Get a customer's full profile with their total order count and spend
     2. List products where inventory is below a threshold
     3. Get orders for a date range with total revenue sum

Claude: [calls elliot_query_sql to verify the data]
        [calls elliot_create_tool for each]

        ✓ Tool 1: get_customer_profile
          SQL: SELECT c.*, COUNT(o.id) as order_count
               FROM customers c
               LEFT JOIN orders o ON o.customer_id = c.id
               WHERE c.id = :customer_id
               GROUP BY c.id
          Parameters: customer_id (string, required)

        ✓ Tool 2: list_low_inventory_products
          SQL: SELECT id, name, sku, price, inventory_count
               FROM products
               WHERE inventory_count < :threshold
               ORDER BY inventory_count ASC
               LIMIT :limit
          Parameters: threshold (integer, required), limit (integer, default 50)

        ✓ Tool 3: get_orders_revenue
          SQL: SELECT COUNT(*) as order_count, SUM(total) as total_revenue,
                      MIN(created_at) as from_date, MAX(created_at) as to_date
               FROM orders
               WHERE created_at >= :from AND created_at <= :to
               AND (:status IS NULL OR status = :status)
          Parameters: from (date, required), to (date, required), status (string, optional)

        Want me to test any of these against your live data?
```

### Step 6: Test tools

```
You: Yes, test get_customer_profile with customer_id = "cust_001"

Claude: [calls elliot_preview_tool]

        Result: { "id": "cust_001", "name": "Acme Corp", "email": "...",
                  "total_spent": 12450.00, "order_count": 47 }
        Latency: 234ms ✓
```

### Step 7: Build and start the connector

```
You: Build the connector and start it.

Claude: [calls elliot_build_connector]
        [calls elliot_start_runtime]

        ✓ Connector built: shopOS-connector v1.0.0
          3 tools | 0 skills

        ✓ Connector runtime started on http://localhost:3001/mcp

        Add to your agent config:
        { "shopOS": { "type": "http", "url": "http://localhost:3001/mcp" } }

        Restart your agent and your connector is live.
```

---

## 9. Workspace Directory Structure

The plugin writes all state to `.elliot/` in the working directory:

```
.elliot/
├── session.json          # sources, tools, skills, product context
├── secrets.enc           # encrypted API keys (AES-256-GCM)
├── connector.json        # latest built connector
├── audit.ndjson          # append-only audit log (newline-delimited JSON)
└── eval/
    ├── suite-1.json      # evaluation suites
    └── results/
        └── run-2025-01-01T10:00:00.json
```

`.elliot/secrets.enc` is excluded from git via `.gitignore` (auto-added by the plugin on first use).

---

## 10. Environment Variables

The MCP plugin reads these from environment or `.elliot/.env`:

```bash
ELLIOT_PORT=3000                        # plugin HTTP port (default: 3000)
ELLIOT_WORKSPACE_DIR=./.elliot          # where to write state (default: cwd/.elliot)
ELLIOT_MAX_ROWS=10000                   # max rows per table load
ELLIOT_MAX_PAGES=100                    # max pagination pages to follow
ELLIOT_TIMEOUT_MS=30000                 # HTTP request timeout
ELLIOT_RATE_LIMIT=60                    # max tool calls/minute in runtime
ELLIOT_LOG_LEVEL=info                   # debug | info | warn | error
```

---

## 11. Common Development Commands

```bash
# First-time setup
pnpm install && pnpm setup

# Start everything (plugin :3000 + Studio :5173)
pnpm dev

# Build all packages
pnpm build

# Run tests across everything
pnpm test

# Typecheck all packages
pnpm typecheck

# Add a new shadcn component to Studio
pnpm --filter @elliot/studio dlx shadcn@latest add <component>

# Serve an existing connector (Phase 2+)
pnpm --filter @elliot/connector-runtime run build
node packages/connector-runtime/dist/index.js --connector .elliot/connector.json
```
