---
name: discover-source
description: Discover a data source (REST API, Postgres, MySQL, or local file) and register it with Elliot so its tables and endpoints become queryable. Use as the first step of building a new connector.
when_to_use: Trigger when the user says "I have an API at...", "wrap my database", "connect my Postgres", "wrap this CSV file", or when build-connector skill needs a source to draft tools against.
argument-hint: "[source-url-or-connection-string]"
allowed-tools: Bash mcp__elliot__*
---

# Discover Source Workflow

You are identifying the user's data source and registering it with Elliot. The
goal is to land at a state where `elliot_discover_source` has succeeded and the
next skill (`build-connector`) can draft tools against the discovered schema.

## Step 0 — Set context if not already set

If `elliot_get_session_state` shows no `product_context`, call:
- `elliot_set_context` with `name` (slug-style, e.g. `acme-crm`) and a
  one-sentence `description`.

If the user hasn't told you these yet, ask in one combined question. Don't ask
two separate questions.

## Step 1 — Identify the source type

Ask the user (one question, listing the options):

> "What kind of source is this? **REST API**, **Postgres**, **MySQL**, or a
> **file** (CSV / JSON / JSONL)?"

Map their answer to a `source_type`:

| User says | `source_type` arg |
|-----------|-------------------|
| "REST", "API", URL ending in `/api` | `rest` (aliases: `api`, `http`) |
| "Postgres", "PG", `postgres://` | `postgres` (alias: `db`, `postgresql`) |
| "MySQL", `mysql://` | `mysql` |
| "CSV", "JSON", "JSONL", a `.csv` / `.json` file | `file` (aliases: `csv`, `json`) |

If the user has an **OpenAPI spec or Postman collection**, this is the wrong
skill — switch to `onboard-product` and call `elliot_import_api_collection`
instead. `elliot_discover_source` does **not** ingest OpenAPI/Postman.

If the user wants to wrap a **SQLite database**, Elliot does not support it as
a source today; ask them to export the relevant tables to CSV or JSON first.

## Step 2 — Collect the right `config` fields for that source type

`elliot_discover_source` takes exactly three arguments:

```
elliot_discover_source(source_type=<one of above>, config=<dict>, name=<table name>)
```

Everything that varies by source type goes inside the `config` dict. Ask in one
batched message — never field-by-field, it wastes turns.

### REST

```json
{
  "url": "https://api.acme.com/v1/customers",
  "method": "GET",
  "auth": {
    "type": "bearer",
    "secret_key": "{{ env:ACME_API_TOKEN }}"
  },
  "data_path": "data",
  "pagination": {"strategy": "offset", "page_size": 50, "max_pages": 10}
}
```

- `url` — full endpoint URL the agent will fetch from.
- `method` — `GET` (default) or `POST`.
- `auth.type` — one of `bearer`, `api_key`, `basic`, `oauth2`.
- `auth.secret_key` — env-var template `{{ env:VAR_NAME }}`. **Never the
  actual credential value.** A bare env var name (e.g. `"ACME_API_TOKEN"`)
  also works.
- `data_path` (optional) — JMESPath into the response where the list lives
  (e.g. `data`, `results.items`).
- `pagination` (optional) — `strategy` is `cursor`, `offset`, `page`,
  `link_header`, or `none`. Add `cursor_field` or `next_url_field` if the
  upstream returns them under a non-default key.

### Postgres / MySQL

```json
{
  "url": "{{ env:DATABASE_URL }}",
  "table": "orders"
}
```

- `url` — connection string as `{{ env:VAR_NAME }}`. **Never the literal URL.**
- `table` (optional) — single table to materialize.
- `query` (optional) — custom `SELECT` to run instead of `SELECT * FROM table`.

### File (CSV / JSON / JSONL)

```json
{
  "path": "/abs/path/to/data.csv",
  "format": "csv"
}
```

- `path` — absolute or workspace-relative path. Must live under the file
  reader's allowlist.
- `format` — `csv`, `json`, or `jsonl`.
- `encoding` (optional, default `utf-8`), `delimiter` (optional, default `,`).

**If the file is on the user's machine and not under Elliot's workspace**,
upload it first with `elliot_upload_file(file_name, content, encoding="text")`.
It returns a `managed_path` already inside the allowlist — use that as
`config.path`.

## Step 3 — Call `elliot_discover_source`

Pass the collected arguments. The tool probes the source, materializes its
rows into in-memory SQLite, and returns
`{source_id, table_name, row_count, columns, warnings}`.

After it succeeds, you can inspect what landed with:
- `elliot_list_sources` — every source registered in the session.
- `elliot_preview_source(table_name, limit=10)` — first N rows.
- `elliot_profile_source(table_name)` — column statistics.

## Step 4 — Confirm and route to next skill

Print a one-line summary: "Discovered <N> tables" or
"Discovered <N> rows in `<table_name>`". Then tell the user:

> "Ready to draft tools. I'll switch to `build-connector` now."

Invoke `prompts/get name=build-connector` to continue.

## Managing sources during iteration

- `elliot_refresh_source(source_id)` — re-fetch from the origin (use after
  the upstream changes).
- Removing a source is a user-driven action: ask the user to click "Remove"
  on the Studio Sources page (or Cloud dashboard) when you loaded the wrong
  thing or want to start over.

## Failure handling

If `elliot_discover_source` returns an error:

| Error code | Action |
|-----------|--------|
| `SOURCE_UNREACHABLE` | Confirm the URL / env var with the user, retry once. If it still fails, stop and ask. |
| `AUTH_FAILED` | Confirm the env var name and that the variable is actually set in the shell. Do **not** ask the user to paste the secret. |
| `SCHEMA_NOT_FOUND` | List available schemas (the error `details` will include them) and ask which one. |
| anything else | Surface the error message verbatim and ask the user how they want to proceed. |

Do not retry blindly. Errors from Elliot are actionable by design — read the
`details` field before retrying.
