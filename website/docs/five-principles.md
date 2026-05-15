# The five principles

These five rules drive every technical decision in Elliot. They are also what the linter checks before any tool ships.

## 1. Tool descriptions are contracts

Verb-first, unambiguous, typed. The description must let the agent decide *whether to call this tool* without reading the implementation.

::: tip Good
`list_animals` — "Return all animals, optionally filtered by species. Returns up to 100 rows."
:::

::: warning Bad
`animals` — "Get animals data."
:::

## 2. Results are sized for the context window

A tool that dumps a 10MB JSON response is broken, even if the data is correct. Defaults:

- Pagination is on for every collection
- Wide objects ship a projection (only the fields the description claims)
- Aggregation tools return the aggregate, not the raw rows

## 3. Errors are actionable

Every error has the shape:

```json
{
  "error": {
    "code": "VALIDATION_MISSING_PARAMETER",
    "message": "The 'species' parameter is required for this query.",
    "details": { "parameter": "species" }
  }
}
```

The `code` tells the agent which class of error this is. The `message` tells it (and the user) what happened. The `details` give the agent enough state to recover or escalate.

## 4. Every session is observable

Every tool call is appended to an NDJSON audit log with:

- timestamp
- tool id + arguments
- rows returned + bytes returned
- duration
- error (if any)
- session id

Studio reads from the same log. No call is invisible.

## 5. The platform itself is agentic

Elliot exposes its own builder loop — `discover-source`, `build-connector`, `lint-connector`, `run-eval`, `deploy-connector` — as MCP tools. An agent can build a connector for your API just by being pointed at Elliot. The platform is a product agents use to build agentic products.

## How the linter applies them

`elliot lint my.connector.json` returns a structured report:

```
my.connector.json
  tools/list_animals
    ✓ verb-first description
    ✓ all parameters typed
    ✓ return shape documented
    ! description does not mention pagination behaviour
```

A warning means "the agent will probably still pick this tool correctly". A failure means "the agent cannot use this tool safely" — the connector won't deploy.
