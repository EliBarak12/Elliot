# Elliot — Product Overview

## What is Elliot?

Elliot is a **connector platform** that turns any REST API or database into a set of MCP (Model Context Protocol) tools that AI coding agents (Claude Code, Codex, etc.) can call directly.

A developer writes a single `.connector.json` file describing their data sources and the SQL queries they want to expose as tools. Elliot does the rest: schema generation, HTTP fetching, SQL execution, auth, and audit logging.

---

## User Journey

```mermaid
journey
    title Developer builds a connector and uses it with Claude Code
    section Write connector
        Write .connector.json: 5: Developer
        Validate with elliot-core: 4: Developer
    section Test in Studio
        Open Elliot Studio: 5: Developer
        Browse sources and tools: 5: Developer
        Run a tool manually: 5: Developer
        Check audit log: 3: Developer
    section Use with AI
        Point Claude Code at :3000: 5: Developer
        Claude discovers tools: 5: Claude Code
        Claude calls tool, gets data: 5: Claude Code
        Claude answers question: 5: Claude Code
    section Monitor
        View audit log in Studio: 4: Developer
        Check metrics page: 3: Developer
```

---

## Studio Pages & Navigation

```mermaid
flowchart TD
    App(["Elliot Studio"])
    Nav["Top nav: connector selector + status badge"]

    App --> Nav
    Nav --> Dashboard
    Nav --> Tools
    Nav --> Skills
    Nav --> Playground
    Nav --> Metrics

    Dashboard["📊 Dashboard\n─────────────\n• List of sources\n• Source type badge (REST / PG)\n• Auth status indicator\n• Row count preview"]

    Tools["🔧 Tools\n─────────────\n• List of tools with category badge\n  READ / WRITE / ACTION\n• Click → parameter form\n• Run button → data table result\n• SQL shown in expandable panel"]

    Skills["⚡ Skills\n─────────────\n• List of skills\n• Which tools each skill uses\n• Prompt template preview\n• Run skill → result"]

    Playground["🎮 Playground\n─────────────\n• Select tool or skill\n• Fill in parameters (auto-form)\n• Run → raw JSON / table toggle\n• Response time shown\n• Copy result button"]

    Metrics["📈 Metrics\n─────────────\n• Audit log table (last N calls)\n• Columns: time, tool, args,\n  rows returned, duration, error\n• Filter by tool name\n• Export as CSV"]
```

---

## Studio UI Component Tree

```mermaid
flowchart TD
    Root["App.tsx"]
    Root --> Layout
    Layout --> TopNav["TopNav\n(ConnectorSelect + StatusBadge)"]
    Layout --> Router["React Router outlet"]

    Router --> DashboardPage["DashboardPage"]
    Router --> ToolsPage["ToolsPage"]
    Router --> SkillsPage["SkillsPage"]
    Router --> PlaygroundPage["PlaygroundPage"]
    Router --> MetricsPage["MetricsPage"]

    DashboardPage --> SourceCard["SourceCard × N"]
    SourceCard --> AuthBadge["AuthBadge"]
    SourceCard --> TypeBadge["TypeBadge (REST / PG)"]

    ToolsPage --> ToolList["ToolList"]
    ToolList --> ToolRow["ToolRow × N"]
    ToolRow --> CategoryBadge["CategoryBadge"]
    ToolsPage --> ToolDetail["ToolDetail panel"]
    ToolDetail --> ParamForm["ParamForm"]
    ToolDetail --> ResultTable["ResultTable"]
    ToolDetail --> SqlViewer["SqlViewer (collapsible)"]

    PlaygroundPage --> ToolSelector["ToolSelector dropdown"]
    PlaygroundPage --> ParamForm
    PlaygroundPage --> ResultTable
    PlaygroundPage --> TimingBadge["TimingBadge (ms)"]

    MetricsPage --> AuditTable["AuditTable"]
    AuditTable --> FilterBar["FilterBar"]
    AuditTable --> ExportButton["ExportButton (CSV)"]
```

---

## State Shape (Zustand)

```mermaid
classDiagram
    class AppStore {
        +string activeConnectorSlug
        +ConnectorSummary[] connectors
        +ToolDefinition[] tools
        +SkillDefinition[] skills
        +SourceConfig[] sources
        +QueryResult lastResult
        +AuditEntry[] auditLog
        +boolean loading
        +string|null error
        +setConnector(slug)
        +runTool(toolId, args)
        +refreshAudit()
    }
```

---

## What a `.connector.json` looks like

```json
{
  "name": "Pet Store API",
  "slug": "petstore",
  "version": "1.0.0",
  "sources": [
    {
      "id": "animals",
      "name": "Animals endpoint",
      "type": "rest",
      "url": "https://api.example.com/animals",
      "data_path": "items",
      "auth": {
        "type": "api_key",
        "secret_key": "PETSTORE_API_KEY",
        "header_name": "X-Api-Key"
      }
    }
  ],
  "tools": [
    {
      "id": "list_animals",
      "name": "List animals",
      "description": "Return all animals, optionally filtered by species",
      "category": "READ",
      "sql": "SELECT * FROM animals WHERE (:species IS NULL OR species = :species)",
      "parameters": [
        {
          "name": "species",
          "type": "string",
          "description": "Filter by species (optional)",
          "required": false
        }
      ]
    }
  ],
  "skills": [
    {
      "id": "animal_report",
      "name": "Animal population report",
      "description": "Summarise all animals grouped by species",
      "tool_ids": ["list_animals"],
      "prompt_template": "Using the results of list_animals, group by species and return counts."
    }
  ]
}
```

---

## Key Design Decisions

| Decision | Choice | Why |
|---|---|---|
| MCP transport | StreamableHTTP | Works with Claude Code out of the box; no stdio process needed |
| Query engine | Ephemeral in-memory SQLite | No persistent state; each call is fresh; jmespath handles nested API responses |
| Cache strategy | TTL + mtime | Hot-reload without restart; 30 s TTL catches most changes |
| Audit format | NDJSON | Greppable, streamable, importable into any log tool |
| Auth secrets | Env vars / secrets file | Never stored in connector.json; safe to commit connector definitions |
| Studio stack | React + Vite + Zustand | Fast dev, minimal boilerplate, easy MCP client integration |
