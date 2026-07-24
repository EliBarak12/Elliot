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

#### Shared vs per-user auth

`auth` also takes a `scope` (default `shared`). Pick deliberately — this is the
difference between "one service account for everyone" and "each caller acts as
themselves":

- **`scope: "shared"`** (default, shown above) — one credential, same for every
  caller, from `{{ env:VAR }}`. Use for public/open data or a single service
  account.
- **`scope: "per_user"`** — each end user connects their **own** account; the
  runtime resolves *that caller's* token per request. Use for GitHub / Slack /
  Gmail / any "act as the calling user" source. Each caller authorizes once via
  an OAuth flow; until they do, tools on that source return `AUTH_REQUIRED` with
  a connect URL. **Yes, Elliot supports this** — don't fall back to baking one
  shared token in, and don't add a `token` parameter to a tool.

```json
{
  "url": "https://api.your-provider.com/me",
  "auth": {
    "type": "oauth2",
    "scope": "per_user",
    "secret_key": "{{ user_oauth:your_source }}",
    "oauth2": {
      "authorization_url": "https://your-provider.com/login/oauth/authorize",
      "token_url": "https://your-provider.com/login/oauth/token",
      "scopes": ["..."],
      "client_id_secret": "{{ env:YOUR_PROVIDER_CLIENT_ID }}",
      "client_secret_secret": "{{ env:YOUR_PROVIDER_CLIENT_SECRET }}"
    }
  }
}
```

This is a **template** — replace `url`, the OAuth endpoints, scopes, the
`{{ user_oauth:SOURCE_ID }}` id, and the `{{ env:... }}` names with your actual
provider's (GitHub, Slack, Gmail, …). Don't build the placeholder source as-is.
`secret_key: "{{ user_oauth:your_source }}"` (Elliot Cloud) resolves to the
calling user's stored token; `client_id_secret` / `client_secret_secret` are the
app-level OAuth credentials from `{{ env:... }}`. Read
`elliot://docs/authentication` for the full auth + fetch model before building a
per-user connector.

#### Discovering an `oauth2` source (log in instead of pasting a token)

To learn the schema, discover still needs *a* token to fetch sample rows — but
**never ask the user to paste one** for an `oauth2` source. Instead, log the
builder in the same way their end users will be.

**Step A — tell the user what to set up first (do this proactively).** An
`oauth2` source needs an **OAuth app** registered with the provider. Don't wait
for an error — explain it in plain language the moment you choose `oauth2`:

> "This API uses OAuth, so I won't ask you for a token. Instead you'll log in
> through <Provider>'s own page. First I need you to register an OAuth app so
> the provider knows it's us asking:
> 1. Go to <Provider>'s developer settings and create an **OAuth app**
>    (GitHub: *Settings → Developer settings → OAuth Apps*; most APIs have an
>    equivalent).
> 2. Set an allowed redirect / callback URL that permits **loopback**, i.e.
>    `http://127.0.0.1` (any port). This is the standard 'desktop/native app'
>    setting.
> 3. Copy the **Client ID** and **Client Secret** it gives you and set them as
>    env vars — e.g. `ACME_CLIENT_ID` and `ACME_CLIENT_SECRET`.
> These are your *app's* credentials (registered once for the whole connector),
> NOT a personal token, and your end users will never see them. They're also
> required for the runtime login your users will use, so this is one-time setup."

Reference those env vars in the config as `client_id_secret: "{{ env:ACME_CLIENT_ID }}"`
and `client_secret_secret: "{{ env:ACME_CLIENT_SECRET }}"`.

**Step B — run the login + discover:**

1. Call `elliot_connect_source(source_type, config, name)` with the **same**
   args you'll pass to discover. It returns
   `{status: "awaiting_authorization", authorize_url, connect_id}`.
2. Show the `authorize_url` to the user: "Open this to log in to <API>." They
   sign in on the provider's own page; Elliot catches the redirect on a local
   loopback port and captures the token underground.
3. Call `elliot_discover_source(source_type, config, name)`. It blocks until the
   login completes, then uses that token to fetch the schema. If it returns
   `AUTH_REQUIRED` ("still waiting"), the user hasn't finished — wait and retry.

**If `elliot_connect_source` returns `AUTH_REQUIRED` saying the client id isn't
set**, the user hasn't done Step A (or the env var name doesn't match). Re-state
Step A — register the OAuth app and export the client id/secret env vars — then
retry. Do **not** work around it by switching to a pasted token.

The builder token from this login is used for discovery only and is never
written into the connector file — end users authenticate themselves at runtime.

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
| `UPSTREAM_FETCH_FAILED` | The probe couldn't reach or read the source — an unreachable URL, a wrong connection string, or (for a DB) a missing/mis-named table. The message names the URL/reason; confirm the URL, env var, or table name with the user and retry once. If it still fails, stop and ask. |
| `AUTH_FAILED` | Confirm the env var name and that the variable is actually set in the shell. Do **not** ask the user to paste the secret. |
| `AUTH_REQUIRED` (from `elliot_discover_source` / `elliot_connect_source`, "client id is not set") | The user hasn't registered the OAuth **app** yet. Tell them to create an OAuth app with the provider, allow a `http://127.0.0.1` loopback redirect, and export the **Client ID** + **Client Secret** as the env vars named in `client_id_secret` / `client_secret_secret`. Then retry. These are app-level, one-time, not a personal token. |
| `AUTH_REQUIRED` (login) | An `oauth2` source needs a login. During **discovery**, call `elliot_connect_source` (same args), surface the returned `authorize_url`, let the user log in, then retry discover. At **runtime**, a `per_user` source surfaces connect URL(s) in `details.connect`; the user logs in once, then retry. Never paste a token. |
| `VALIDATION_ERROR` | The `config` shape is wrong for this `source_type` (a missing/misnamed field, a bad `encoding`, an unsupported file extension). Read the message, fix the offending field, and retry. |
| `FILE_NOT_FOUND` / `FILE_TOO_LARGE` / `INVALID_FILE_NAME` | A file source problem — a path outside the allowlist, a too-large upload, or a bad name. Upload the file with `elliot_upload_file` and use the returned `managed_path`. |
| anything else | Surface the error message verbatim and ask the user how they want to proceed. |

Do not retry blindly. Errors from Elliot are actionable by design — read the
`details` field before retrying.
