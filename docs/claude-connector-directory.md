# Submitting Elliot to Anthropic's Connectors directory

This document is the working packet for getting Elliot listed in the **built-in
Connectors directory** inside Claude.ai and the Claude apps — the curated list
users browse, rather than the "Add custom connector → paste a URL" flow (which
already works today; see the README).

Listing in the directory is a **review process run by Anthropic**, not
self-serve. The sections below collect everything the intake form asks for so a
submission can be filled out in one pass.

---

## 1. Readiness checklist

The hard requirements for a remote MCP connector. Elliot's hosted backend
(`elliot-cloud-`) already satisfies the technical ones — the source of truth is
`apps/api/src/elliot_cloud/routers/oauth.py` and `runtime/asgi.py`.

| Requirement | Status | Where |
|---|---|---|
| Public remote MCP server over HTTPS (Streamable HTTP) | ✅ | `https://api.elliot-cloud.com/b/mcp` |
| OAuth 2.1 authorization-code flow with **mandatory S256 PKCE** | ✅ | `GET /oauth/authorize`, `POST /oauth/token` |
| Dynamic Client Registration (RFC 7591) | ✅ | `POST /oauth/register` |
| Protected-resource metadata (RFC 9728) | ✅ | `/.well-known/oauth-protected-resource/b/mcp` |
| Authorization-server metadata (RFC 8414) | ✅ | `/.well-known/oauth-authorization-server` |
| `WWW-Authenticate` header on 401 pointing at the metadata | ✅ | `_send_unauthorized_for_oauth` in `runtime/asgi.py` |
| Discovery documents readable cross-origin (`Access-Control-Allow-Origin: *`) | ✅ | `_public_metadata` in `routers/oauth.py` |
| Per-user identity, revocable grants | ✅ | `scope: per_user`, `/api/me/oauth-grants` |
| Privacy policy + Terms of Service URLs | ✅ drafted (have counsel review) | `website/legal/privacy.md`, `website/legal/terms.md` |
| Support contact | ✅ | support@elliot-cloud.com / GitHub Security Advisories |
| Verb-first, typed tool descriptions sized for context | ✅ | enforced by the connector linter (five principles) |

> **Open item before submission:** have counsel review the drafted privacy
> policy and terms (`website/legal/`), then confirm they publish to their stable
> URLs once the docs site deploys:
> - https://elibarak12.github.io/Elliot/legal/privacy
> - https://elibarak12.github.io/Elliot/legal/terms
>
> Everything else in the table is already shipping.

### Not yet implemented (decide before submitting)

- **Refresh tokens.** The token endpoint issues short-lived access tokens and
  supports only the `authorization_code` grant — there is no `refresh_token`
  grant. Users re-run the consent flow when a token expires. This is acceptable
  for review but worth weighing against UX; adding refresh-token support is a
  schema + token-model change and should be scoped as its own task.

---

## 2. Listing copy (ready to paste)

**Name:** Elliot

**Tagline:** Turn any API or database into agent-ready tools.

**Short description (≤ 80 chars):**
Build, deploy, and observe agent-ready MCP tools for any API or database.

**Long description:**
> Elliot turns the products you already have — REST APIs, SQL databases, files —
> into tools AI agents can use *well*: minimal token usage, structured errors the
> agent can recover from, and a full trace of every call. Connect Elliot to
> Claude to design, validate, deploy, and observe connector tool sets, with every
> tool linted against five concrete principles before it ships.

**Categories:** Developer tools · Databases · Productivity

**Keywords:** mcp, connectors, agent-tools, api, database, observability

**Icon:** `website/public/logo-mark.svg`

**Homepage:** https://github.com/EliBarak12/Elliot
**Documentation:** https://elibarak12.github.io/Elliot/

---

## 3. Scopes and data handling (for the review form)

- **Scope requested:** `mcp` (single scope). Each user authenticates with their
  own identity (`scope: per_user`); there is no shared service credential.
- **What Elliot accesses on the user's behalf:** only the connector tools the
  user's workspace has deployed. Elliot does not read Claude conversation
  content beyond the tool arguments the agent sends.
- **Data retention:** tool calls are recorded to an audit log (tokens, latency,
  arguments, errors) for observability. Document the retention window and how a
  user purges it in the privacy policy.
- **Secrets:** upstream API keys are referenced as `{{ env:NAME }}` /
  `{{ user_oauth:SOURCE }}` and resolved at runtime — never stored in connector
  JSON and never returned to the agent. See `SECURITY.md`.
- **Network safety:** outbound REST fetches are SSRF-guarded (private, loopback,
  and cloud-metadata hosts blocked); tool SQL is validated read-only.
- **Revocation:** users revoke Claude's grant from **Connected agents** in the
  Elliot dashboard (`DELETE /api/me/oauth-grants/{id}`), which immediately blocks
  further calls.

---

## 4. Required legal/support pages

These now live in the docs site (`website/legal/`) and publish at:

- **Privacy policy** — https://elibarak12.github.io/Elliot/legal/privacy
  (what's collected — audit-log fields, retention, deletion, sub-processors,
  contact).
- **Terms of service** — https://elibarak12.github.io/Elliot/legal/terms
  (acceptable use, availability, liability).
- **Support** — support@elliot-cloud.com and the GitHub Security Advisories link in
  `SECURITY.md` for vulnerability reports.

Both are drafts written against Elliot's actual data handling — have legal
counsel review them before the submission.

---

## 5. How to verify the connector before submitting

Reviewers will run the exact flow a user runs. Reproduce it first:

1. In Claude (web or desktop) → **Settings → Connectors → Add custom connector**.
2. Paste `https://api.elliot-cloud.com/b/mcp`.
3. Confirm the browser is redirected to the Elliot consent screen, **Allow**
   returns Claude to a connected state, and Elliot's tools appear in the picker.
4. Run a tool call and confirm it executes and is traced in the dashboard.
5. Revoke the grant under **Connected agents** and confirm subsequent calls 401.

A quick automated sanity check of the discovery surface:

```bash
curl -s https://api.elliot-cloud.com/.well-known/oauth-authorization-server | jq .
curl -s https://api.elliot-cloud.com/.well-known/oauth-protected-resource/b/mcp | jq .
# Expect 200 JSON with S256 advertised and Access-Control-Allow-Origin: *
curl -si https://api.elliot-cloud.com/b/mcp -X POST \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep -i www-authenticate
# Expect: 401 with WWW-Authenticate: Bearer resource_metadata="…/b/mcp"
```

---

## 6. Where to submit

Anthropic's connector/partner intake is linked from the remote-MCP connector
docs:

- Building custom connectors via remote MCP servers —
  https://support.anthropic.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers
- MCP connector documentation — https://docs.claude.com

Submit the listing copy (§2), scopes/data-handling answers (§3), and the legal
URLs (§4) through the intake form, then respond to the review thread.
