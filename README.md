# Elliot — AI Connector Platform

> Give any existing product an AI-native interface — without rewriting a line of it.

Elliot is a **TypeScript monorepo** that lets you wrap your existing APIs, databases, and files into a structured **Connector**: a versioned, locally-runnable MCP server that AI agents can discover and interact with.

**Phase 1** ships as a **Claude Code MCP plugin**. The AI agent guides you through a conversation, fetches your APIs, flattens the JSON into in-memory SQLite, and helps you define business-domain tools on top of your data. The result is a `.connector.json` file you run locally — and connect directly to Claude Desktop, Claude Code, or GitHub Copilot.

---

## How Phase 1 Works

```
You install the Elliot MCP plugin into Claude Code.

Claude Code asks you:
  "What product are you building a connector for?"
  "What APIs does it have?"
  "What databases or files?"
  "What business operations do you want to expose as AI tools?"

Elliot:
  → Fetches your APIs and flattens the JSON into in-memory SQLite
  → Lets Claude query the data with SQL to understand your schema
  → Helps you define tools: name, description, parameters, SQL query
  → Packages everything as a .connector.json file
  → Starts a local MCP server on :3001

You paste the server URL into Claude Desktop config.
Your product is now AI-native.
```

---

## Repository Structure

```
elliot/
├── packages/
│   ├── core/               @elliot/core      — Source fetching, SQLite engine, tool builder
│   ├── mcp-plugin/         @elliot/mcp-plugin — MCP server for Claude Code (stdio)
│   ├── connector-runtime/  @elliot/connector-runtime — Run a .connector.json as MCP server
│   └── studio/             @elliot/studio    — React + Vite + shadcn/ui dashboard
└── docs/
    ├── ARCHITECTURE.md     Full system design, data models, edge cases
    ├── DEVELOPMENT_GUIDE.md TypeScript setup + build walkthrough
    ├── CORE_CONCEPTS.md    Tools, Skills, Prompts, Connectors explained
    ├── PRODUCT_SPECIFICATION.md Full product spec (all phases)
    └── DEVELOPMENT_MISSIONS.md Mission-by-mission build plan
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | TypeScript 5.x (strict) |
| MCP Server | `@modelcontextprotocol/sdk` |
| SQLite | `better-sqlite3` |
| Schema validation | `zod` |
| HTTP client | `undici` |
| Testing | `vitest` |
| Studio frontend | React 18 + Vite + Tailwind CSS + shadcn/ui |
| State management | Zustand |
| Monorepo | pnpm workspaces |

---

## Quick Start

```bash
# Clone and install
git clone https://github.com/elibarak12/elliot.git
cd elliot
pnpm install

# Build all packages
pnpm build

# Add MCP plugin to Claude Code (~/.claude/claude_desktop_config.json)
pnpm --filter @elliot/mcp-plugin run install-claude

# Or run the Studio dashboard
pnpm --filter @elliot/studio run dev
```

See [DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md) for the complete walkthrough.

---

## Documentation

| Doc | Description |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Full system diagram, data models, SQLite engine, MCP tool catalog, evaluation framework, 30+ edge cases |
| [DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md) | TypeScript monorepo setup, per-package instructions, testing guide, Phase 1 walkthrough |
| [CORE_CONCEPTS.md](docs/CORE_CONCEPTS.md) | Products, Endpoints, Tools, Skills, Prompts, Connectors — the domain model |
| [PRODUCT_SPECIFICATION.md](docs/PRODUCT_SPECIFICATION.md) | All-phases product spec, user stories, KPIs |
| [DEVELOPMENT_MISSIONS.md](docs/DEVELOPMENT_MISSIONS.md) | 10 sequential build missions with acceptance criteria |

---

## License

MIT
