# Connector spec

A connector is a single JSON file. This page documents the full schema.

## Top-level shape

```json
{
  "name": "Pet Store API",
  "slug": "petstore",
  "version": "1.0.0",
  "sources": [ /* ... */ ],
  "tools":   [ /* ... */ ],
  "skills":  [ /* ... */ ]
}
```

| Field | Required | Description |
|---|---|---|
| `name` | yes | Human-readable display name |
| `slug` | yes | Stable identifier (`a-z0-9-`) used in URLs and audit logs |
| `version` | yes | SemVer — bump when the contract changes |
| `sources` | yes | One or more data sources (see below) |
| `tools` | yes | One or more agent-callable tools |
| `skills` | no | Prompt templates that orchestrate tools |

## Sources

### REST

```json
{
  "id": "animals",
  "type": "rest",
  "url": "https://api.example.com/animals",
  "data_path": "items",
  "auth": {
    "type": "api_key",
    "secret_key": "PETSTORE_API_KEY",
    "header_name": "X-Api-Key"
  }
}
```

`data_path` is a [JMESPath](https://jmespath.org/) expression that extracts the array of records from the response envelope.

### PostgreSQL / MySQL

<div v-pre>

```json
{
  "id": "orders",
  "type": "postgres",
  "dsn": "{{ env:ORDERS_DATABASE_URL }}",
  "table": "orders"
}
```

</div>

### CSV / JSON file

```json
{
  "id": "regions",
  "type": "csv",
  "path": "./data/regions.csv"
}
```

### Auth types

| Type | Required fields |
|---|---|
| `none` | — |
| `api_key` | `secret_key`, `header_name` |
| `bearer` | `secret_key` |
| `basic` | `user_secret_key`, `pass_secret_key` |

Secrets always resolve from process env vars. **Never** put a key directly in the JSON.

## Tools

```json
{
  "id": "list_animals",
  "name": "List animals",
  "description": "Return all animals, optionally filtered by species. Returns up to 100 rows.",
  "category": "READ",
  "sql": "SELECT * FROM animals WHERE (:species IS NULL OR species = :species) LIMIT 100",
  "parameters": [
    {
      "name": "species",
      "type": "string",
      "description": "Filter by species (optional)",
      "required": false
    }
  ]
}
```

| Field | Required | Description |
|---|---|---|
| `id` | yes | `snake_case`, stable |
| `name` | yes | Display name |
| `description` | yes | Verb-first. The linter rejects vague descriptions. |
| `category` | yes | `READ`, `WRITE`, or `ACTION` |
| `sql` | yes | Parameterised — bind with `:name`, never `+` |
| `parameters` | yes | Typed parameter list (may be empty) |

Parameter types: `string`, `int`, `float`, `bool`, `date`, `datetime`.

## Skills

```json
{
  "id": "animal_report",
  "name": "Animal population report",
  "description": "Summarise all animals grouped by species.",
  "tool_ids": ["list_animals"],
  "prompt_template": "Using the results of list_animals, group by species and return counts."
}
```

Skills are surfaced through MCP `prompts/list` — agents see them alongside tools.

## Secrets in env vars

Inside any string value in the connector, you can interpolate <code v-pre>{{ env:VAR_NAME }}</code>. The runtime substitutes from `os.environ` at request time. Useful for DSNs, URLs that vary by env, etc.

## Hot reload

The runtime watches connector files on disk. mtime + 30s TTL means edits show up in agents and Studio within seconds — no service restart needed.

## Validation

`elliot lint my.connector.json` runs the full schema check plus the [five principles](./five-principles) audit on every tool. Run it locally and in CI.
