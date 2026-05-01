# Elliot — AI Connector Platform

> Transform any existing product into an AI-native experience.

Elliot is a platform that lets teams wrap their existing APIs, databases, and services into a structured **Connector** — a versioned, deployable AI interface that agents can discover, understand, and use.

You bring your existing product. Elliot gives you the layer that makes it agent-ready.

---

## The Core Idea

Most products today weren't built for AI agents. They have REST APIs, databases, and action endpoints — but no structured way for an AI to understand what they can do, when to call them, or how to chain them together.

Elliot solves this by letting you define:

| Concept | What it is |
|---|---|
| **Tool** | A single atomic operation mapped from one of your API endpoints |
| **Skill** | A multi-step composed workflow that chains Tools with AI orchestration |
| **Prompt** | A system prompt or template that guides agent behavior |
| **Connector** | The packaged, versioned, deployable artifact combining all of the above |

Agents connect to your Connector URL and interact with your product as a first-class AI integration.

---

## How It Works

```
Your Existing Product
  (REST APIs / Databases / Action Endpoints)
           ↓
    ┌──────────────────────────────┐
    │       Elliot Platform        │
    │  ① Import your product API   │
    │  ② Build Tools from endpoints│
    │  ③ Compose Skills (workflows)│
    │  ④ Define Prompts            │
    │  ⑤ Deploy your Connector     │
    └──────────────────────────────┘
           ↓  Unique Connector URL
    AI Agents
  (Claude / GPT / LangChain / Custom)
```

---

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | Full technical architecture, data model, API design, security |
| [Product Specification](docs/PRODUCT_SPECIFICATION.md) | MVP features, user stories, KPIs, out-of-scope decisions |
| [Core Concepts](docs/CORE_CONCEPTS.md) | Deep dive on Tools, Skills, Prompts, Connectors |
| [Development Missions](docs/DEVELOPMENT_MISSIONS.md) | Step-by-step build plan with acceptance criteria |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 15, TypeScript, Tailwind CSS, shadcn/ui |
| Backend API | Next.js API Routes |
| Connector Runtime | Python FastAPI (JSON-RPC 2.0 / MCP) |
| Database & Auth | Supabase (PostgreSQL + Auth + Storage) |
| AI Integration | Anthropic Claude (tool generation + skill orchestration) |
| Frontend Deploy | Vercel |
| Runtime Deploy | Railway / Render (Docker) |

---

## License

MIT
