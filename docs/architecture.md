# Elliot — Full System Architecture

## System Overview

```mermaid
graph TB
    subgraph Client["Client Layer"]
        CC["🤖 Claude Code / AI Agent"]
        Studio["🖥️ Elliot Studio\nReact + Vite :5173"]
    end

    subgraph Services["Elliot Services"]
        Plugin["📦 elliot-mcp-plugin\nFastMCP + FastAPI\n:3000"]
        Runtime["⚙️ elliot-connector-runtime\nFastAPI + FastMCP\n:3001"]
    end

    subgraph Core["elliot-core (shared library)"]
        Types["types.py\nPydantic models"]
        SQLEng["sqlite_engine.py\nIn-memory SQL"]
        Errors["errors.py\nElliotError hierarchy"]
        Flattener["json_flattener.py"]
    end

    subgraph Storage["Local Storage"]
        ConnJSON["📄 *.connector.json\nConnector definitions"]
        AuditLog["📋 audit.ndjson\nAppend-only log"]
        SQLiteMem["🗄️ SQLite in-memory\n(ephemeral per call)"]
    end

    subgraph External["External Data Sources"]
        RESTAPI["🌐 REST APIs"]
        PG[("🐘 PostgreSQL")]
        MySQL[("🐬 MySQL")]
    end

    CC -->|"MCP StreamableHTTP\nPOST /mcp"| Plugin
    Studio -->|"HTTP REST"| Plugin
    Studio -->|"HTTP REST"| Runtime

    Plugin -->|"loads + validates"| ConnJSON
    Plugin -->|"imports"| Core
    Plugin -->|"tool calls delegated"| Runtime

    Runtime -->|"loads + caches (TTL 30s)"| ConnJSON
    Runtime -->|"imports"| Core
    Runtime -->|"GET/POST"| RESTAPI
    Runtime -->|"psycopg2 (thread pool)"| PG
    Runtime -->|"future"| MySQL
    Runtime -->|"append line"| AuditLog
    Runtime -->|"ingest + query"| SQLiteMem

    Core --> Types
    Core --> SQLEng
    Core --> Errors
    Core --> Flattener
```

---

## Package Dependency Graph

```mermaid
graph LR
    Core["elliot-core\n(Python library)"] 
    Plugin["elliot-mcp-plugin\n(Python service)"]
    Runtime["elliot-connector-runtime\n(Python service)"]
    Studio["elliot-studio\n(TypeScript app)"]

    Core -->|"imported by"| Plugin
    Core -->|"imported by"| Runtime
    Studio -.->|"HTTP only\n(no import)"| Plugin
    Studio -.->|"HTTP only\n(no import)"| Runtime
```

---

## Port Map & Environment Variables

| Service | Port | Entry Point | Key Env Vars |
|---|---|---|---|
| `elliot-studio` | 5173 | `vite dev` | `VITE_PLUGIN_URL`, `VITE_RUNTIME_URL` |
| `elliot-mcp-plugin` | 3000 | `uvicorn elliot_mcp_plugin.server:app` | `ELLIOT_CONNECTORS_DIR`, `LOG_LEVEL` |
| `elliot-connector-runtime` | 3001 | `uvicorn elliot_connector_runtime.server:app` | `ELLIOT_CONNECTOR`, `ELLIOT_AUDIT_LOG`, `LOG_LEVEL` |

---

## Directory Structure

```
elliot/
├── packages/
│   ├── core/                          # elliot-core
│   │   └── src/elliot_core/
│   │       ├── types.py               # ConnectorConfig, ToolDefinition, …
│   │       ├── sqlite_engine.py       # SQLiteEngine: ingest + query
│   │       ├── errors.py              # ElliotError base class
│   │       └── json_flattener.py      # Nested JSON → flat rows
│   │
│   ├── mcp-plugin/                    # elliot-mcp-plugin
│   │   └── src/elliot_mcp_plugin/
│   │       ├── server.py              # create_app() → FastAPI + FastMCP :3000
│   │       ├── session.py             # ElliotSession: per-connector MCP session
│   │       ├── tools/
│   │       │   ├── source_tools.py    # MCP tools for source listing
│   │       │   ├── sql_tools.py       # MCP tools for SQL execution
│   │       │   ├── skill_runner.py    # MCP tools for skill execution
│   │       │   └── context_tools.py   # Connector meta-tools
│   │       ├── logging_config.py      # structlog JSON setup
│   │       └── error_middleware.py    # ElliotError → HTTP JSON
│   │
│   ├── connector-runtime/             # elliot-connector-runtime
│   │   └── src/elliot_connector_runtime/
│   │       ├── server.py              # create_app() → FastAPI + FastMCP :3001
│   │       ├── loader.py              # load_connector(), ConnectorLoadError
│   │       ├── cache.py               # ConnectorCache (TTL + mtime)
│   │       ├── executor.py            # ToolExecutor: fetch + SQL
│   │       ├── audit.py               # AuditLog (NDJSON, thread-safe)
│   │       ├── protocols/
│   │       │   └── openai.py          # /v1/chat/completions endpoint
│   │       ├── logging_config.py
│   │       └── error_middleware.py
│   │
│   └── studio/                        # elliot-studio
│       └── src/
│           ├── main.tsx
│           ├── store/                 # Zustand state
│           ├── client/                # MCP HTTP client
│           └── pages/
│               ├── Dashboard.tsx      # Sources overview
│               ├── Tools.tsx          # Tool browser + runner
│               ├── Skills.tsx         # Skill browser
│               ├── Playground.tsx     # Interactive tool tester
│               └── Metrics.tsx        # Audit log viewer
│
├── tasks/                             # Implementation task specs
│   ├── 01-monorepo-setup/
│   ├── 02-core-library/
│   ├── 03-mcp-plugin/
│   ├── 04-connector-runtime/
│   ├── 05-studio-ui/
│   ├── 06-eval-and-polish/
│   └── 07-dx-and-observability/
│
├── docs/                              # This folder
├── Procfile                           # honcho / foreman dev runner
├── pyproject.toml                     # uv workspace root
└── package.json                       # pnpm workspace root
```

---

## Connector File Schema

```mermaid
classDiagram
    class ConnectorConfig {
        +str name
        +str slug
        +str version
        +list~SourceConfig~ sources
        +list~ToolDefinition~ tools
        +list~SkillDefinition~ skills
    }
    class SourceConfig {
        +str id
        +str name
        +Literal type  rest|postgres|mysql|file
        +str url
        +Optional~str~ table
        +Optional~str~ query
        +Optional~str~ data_path
        +Optional~AuthConfig~ auth
    }
    class ToolDefinition {
        +str id
        +str name
        +str description
        +Literal category  READ|WRITE|ACTION
        +str sql
        +list~ParameterDefinition~ parameters
    }
    class ParameterDefinition {
        +str name
        +Literal type  string|integer|number|boolean
        +str description
        +bool required
    }
    class AuthConfig {
        +Literal type  api_key|bearer|basic
        +str secret_key
        +Optional~str~ header_name
    }
    class SkillDefinition {
        +str id
        +str name
        +str description
        +list~str~ tool_ids
        +str prompt_template
    }

    ConnectorConfig "1" --> "*" SourceConfig
    ConnectorConfig "1" --> "*" ToolDefinition
    ConnectorConfig "1" --> "*" SkillDefinition
    ToolDefinition "1" --> "*" ParameterDefinition
    SourceConfig --> AuthConfig
```
