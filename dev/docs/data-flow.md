# Elliot — Data Flow Diagrams

## 1. Tool Call: End-to-End (Claude Code → Result)

```mermaid
sequenceDiagram
    actor Dev as Developer
    participant CC as Claude Code
    participant Plugin as MCP Plugin :3000
    participant Cache as ConnectorCache
    participant Executor as ToolExecutor
    participant Source as REST API / DB
    participant SQLite as SQLite (in-memory)
    participant Audit as AuditLog

    Dev->>CC: "list all animals"
    CC->>Plugin: MCP tools/call {name: "list_animals", arguments: {}}
    Plugin->>Cache: cache.get(connector_path)
    Cache-->>Plugin: ConnectorConfig (cached or freshly loaded)
    Plugin->>Executor: executor.execute(tool_def, {})
    Executor->>Executor: _extract_table_names("SELECT * FROM animals")
    Executor->>Source: GET https://api.example.com/animals
    Source-->>Executor: {"items": [{"id":1,"name":"Rex"}]}
    Executor->>SQLite: engine.ingest("animals", rows)
    Executor->>SQLite: engine.query("SELECT * FROM animals", {})
    SQLite-->>Executor: [{"id":1,"name":"Rex"}]
    Executor->>Audit: audit.record(tool_id, args, row_count, duration_ms)
    Executor-->>Plugin: QueryResult(rows=[...], tool_id="list_animals")
    Plugin-->>CC: MCP ToolResult {content: [{type:"text", text:"..."}]}
    CC-->>Dev: "Found 1 animal: Rex (dog)"
```

---

## 2. Connector Load & Cache

```mermaid
flowchart TD
    A(["cache.get(path)"])
    B{"Entry\nexists?"}
    C{"TTL\nexpired?"}
    D{"mtime\nchanged?"}
    E(["Return cached\nConnectorConfig"])
    F(["load_connector(path)"])
    G["Read .connector.json"]
    H["JSON parse"]
    I["Pydantic validate\nConnectorConfig"]
    J["Store in cache\n(loaded_at, mtime)"]  
    K(["Return fresh\nConnectorConfig"])
    L(["Raise ConnectorLoadError"])

    A --> B
    B -->|No| F
    B -->|Yes| C
    C -->|Yes| F
    C -->|No| D
    D -->|Yes| F
    D -->|No| E
    F --> G --> H
    H -->|Invalid JSON| L
    H -->|OK| I
    I -->|Schema error| L
    I -->|OK| J --> K
```

---

## 3. Studio UI — Data Flow

```mermaid
sequenceDiagram
    participant User
    participant Studio as Elliot Studio
    participant Store as Zustand Store
    participant Plugin as MCP Plugin :3000
    participant Runtime as Runtime :3001

    User->>Studio: Open Studio
    Studio->>Plugin: GET /health
    Plugin-->>Studio: {status: "ok", connectors: [...]}
    Studio->>Plugin: MCP resources/list
    Plugin-->>Studio: connector list
    Studio->>Store: setConnectors([...])

    User->>Studio: Select connector "Pets"
    Studio->>Plugin: MCP tools/list {connector: "pets"}
    Plugin-->>Studio: [{name:"list_animals",...}]
    Studio->>Store: setTools([...])

    User->>Studio: Click "Run" on list_animals
    Studio->>Runtime: POST /v1/tools/list_animals {}
    Runtime-->>Studio: {rows: [{id:1,name:"Rex"}]}
    Studio->>Store: setLastResult(rows)
    Studio->>User: Show data table

    User->>Studio: Open Metrics tab
    Studio->>Runtime: GET /v1/audit?n=50
    Runtime-->>Studio: [{ts:..., tool_id:..., duration_ms:...}]
    Studio->>User: Show audit table
```

---

## 4. Executor: REST Source with Auth

```mermaid
flowchart LR
    A(["_fetch_rest(source, args)"])
    B["_interpolate(url, args)\nhttps://api.example.com/users/{user_id}
    → https://api.example.com/users/42"]
    C{"source.auth?"}
    D["_build_auth_headers\napi_key / bearer / basic"]
    E["httpx.AsyncClient.get(url, headers)"]
    F{"resp.ok?"}
    G["resp.raise_for_status()"]
    H{"source.data_path?"}
    I["jmespath.search(data_path, data)\ne.g. 'items' or 'data.results'"]
    J{"list?"}
    K(["return rows"])
    L(["return [data]"])
    M(["raise ExecutorError"])

    A --> B --> C
    C -->|Yes| D --> E
    C -->|No| E
    E --> F
    F -->|No| G --> M
    F -->|Yes| H
    H -->|Yes| I --> J
    H -->|No| J
    J -->|list| K
    J -->|dict| L
    J -->|other| M
```

---

## 5. Audit Log Write Path

```mermaid
sequenceDiagram
    participant T1 as Thread 1 (request A)
    participant T2 as Thread 2 (request B)
    participant Lock as threading.Lock
    participant File as audit.ndjson

    T1->>Lock: acquire()
    T2->>Lock: acquire() [BLOCKED]
    Lock-->>T1: acquired
    T1->>File: append line {ts, tool_id, args, rows, ms}
    T1->>Lock: release()
    Lock-->>T2: acquired
    T2->>File: append line {ts, tool_id, args, rows, ms}
    T2->>Lock: release()
    Note over File: Each line is valid JSON\nFile is always append-only\nSafe to tail -f or grep
```

---

## 6. Error Handling Flow

```mermaid
flowchart TD
    A(["Incoming HTTP request"])
    B["Route handler"]
    C{"Raises?"}
    D{"ElliotError\nsubclass?"}
    E["Map code prefix\nto HTTP status"]
    F["JSON response\n{error: {code, message, details}}"]
    G["Log exception\nwith structlog"]
    H["JSON 500\n{error: {code: INTERNAL_ERROR}}"]
    I(["Normal JSON response"])

    A --> B --> C
    C -->|No| I
    C -->|Yes| D
    D -->|Yes| E --> F
    D -->|No| G --> H
```
