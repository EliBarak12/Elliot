---
name: discover-source
description: Discover a data source (REST API, Postgres, MySQL, SQLite) and register it with Elliot so its tables and endpoints become queryable. Use as the first step of building a new connector.
when_to_use: Trigger when the user says "I have an API at...", "wrap my database", "connect my Postgres", "discover this OpenAPI spec", or when build-connector skill needs a source to draft tools against.
argument-hint: "[source-url-or-connection-string]"
allowed-tools: Bash mcp__elliot__*
---

# Discover Source Workflow

You are identifying the user's data source and registering it with Elliot. The goal is to land at a state where `elliot_discover_source` has succeeded and the next skill (`build-connector`) can draft tools against the discovered schema.

## Step 0 — Set context if not already set

If `elliot_session_summary` shows no connector name, call:
- `elliot_set_context` with `connector_name` (slug-style, e.g. `acme-crm`) and a one-sentence `description`.

If the user hasn't told you these yet, ask in one combined question. Don't ask two separate questions.

## Step 1 — Identify the source type

Ask the user (one question, listing the options):

> "What kind of source is this? **REST API**, **Postgres**, **MySQL**, **SQLite**, or an **OpenAPI spec** you can point me at?"

Map their answer:

| User says | `type` arg |
|-----------|------------|
| "REST", "API", URL ending in `/api` | `rest` |
| "Postgres", "PG", `postgres://` | `postgres` |
| "MySQL", `mysql://` | `mysql` |
| "SQLite", `.db` file path | `sqlite` |
| Provides a Swagger/OpenAPI link | `openapi` |

## Step 2 — Collect the right fields for that source type

**For REST / OpenAPI:**
- `url` — base URL (e.g. `https://api.acme.com/v1`)
- `auth_type` — one of `bearer`, `api_key`, `basic`, `none`
- `auth_env_var` — env var name holding the credential (e.g. `ACME_API_KEY`). **Never the value.**
- `pagination` — `cursor`, `offset`, `page`, `link_header`, or `none`

**For Postgres / MySQL:**
- `connection_string_env_var` — env var name (e.g. `ACME_DB_URL`). **Never the actual URL.**
- `schema` — defaults to `public`; ask only if user hints at a non-default schema.

**For SQLite:**
- `path` — file path to the `.db` file.

Ask in one batched message. Never ask field-by-field — that wastes turns.

## Step 3 — Call `elliot_discover_source`

Pass the collected arguments. The tool will probe the source and return a structured discovery result (tables/columns for DBs, endpoints/operations for REST/OpenAPI).

## Step 4 — Confirm and route to next skill

Print a one-line summary: "Discovered <N> tables" or "Discovered <N> endpoints". Then tell the user:

> "Ready to draft tools. I'll switch to `build-connector` now."

Invoke `prompts/get name=build-connector` to continue.

## Failure handling

If `elliot_discover_source` returns an error:

| Error code | Action |
|-----------|--------|
| `SOURCE_UNREACHABLE` | Confirm the URL / env var with the user, retry once. If it still fails, stop and ask. |
| `AUTH_FAILED` | Confirm the env var name and that the variable is actually set in the shell. Do **not** ask the user to paste the secret. |
| `SCHEMA_NOT_FOUND` | List available schemas (the error `details` will include them) and ask which one. |
| anything else | Surface the error message verbatim and ask the user how they want to proceed. |

Do not retry blindly. Errors from Elliot are actionable by design — read the `details` field before retrying.
