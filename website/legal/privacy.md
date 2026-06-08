---
title: Privacy Policy
description: How Elliot Cloud collects, uses, and protects data when you connect an agent to the Elliot MCP service.
---

# Privacy Policy

**Last updated: 8 June 2026**

> This page describes how the hosted **Elliot Cloud** service
> (`api.elliot-cloud.com`) handles data. If you self-host Elliot, you are the
> data controller for your own deployment and this policy does not apply to it.
>
> _This document is provided as a starting point and should be reviewed by legal
> counsel before you rely on it for a production service or a connector-directory
> submission._

## Who we are

Elliot Cloud is operated by the Elliot maintainers. For any privacy question or
request, contact **barak3656@gmail.com**.

## What we collect

We collect only what is needed to run the service and make agent activity
observable:

- **Account identity.** When you sign in, our authentication provider (Clerk)
  supplies a user identifier, email address, and display name. We store these to
  associate your workspace, connectors, and grants with you.
- **Connector definitions.** The connector files you create or deploy, including
  tool descriptions and source configuration. Secrets are **not** stored in
  these files — they are referenced as <code v-pre>{{ env:NAME }}</code> /
  <code v-pre>{{ user_oauth:SOURCE }}</code> and resolved at runtime.
- **Secrets you provide.** Upstream API keys and OAuth tokens you store are
  **encrypted at rest** (Fernet) and are never logged or returned through the
  API.
- **Observability / audit data.** For each agent tool call we record metadata —
  tool name, arguments, token counts, latency, error codes, the client and model
  that called, and timestamps — so you can see and debug agent behaviour.
- **OAuth grants.** When you connect an agent (e.g. Claude) we store the grant
  (which client, which scope, when authorised, when last used) so you can review
  and revoke it.

We do **not** receive or store the content of your conversations with Claude
beyond the arguments an agent explicitly sends to a tool call.

## How we use it

- To operate the service: authenticate you, run connector tools, and inject
  secrets at call time.
- To provide observability: show you traces, token cost, latency, and errors.
- To secure the service: rate limiting, abuse detection, and audit logging.

We do **not** sell personal data, and we do not use your connector data or audit
logs to train models.

## Data handling and security

- Secrets and per-user upstream tokens are encrypted at rest with a key separate
  from the OAuth signing key.
- Outbound requests from connectors are SSRF-guarded (private, loopback, and
  cloud-metadata hosts are blocked) and tool SQL is validated read-only.
- OAuth access tokens are short-lived; refresh tokens are rotated on every use
  and a detected replay revokes the whole grant.

## Retention and deletion

- Audit/observability records are retained to give you a usable history; you can
  delete a connector and its associated records from the dashboard.
- You can revoke any connected agent at any time under **Connected agents**,
  which immediately blocks further access.
- To delete your account and associated data, contact **barak3656@gmail.com**.

## Sub-processors

We rely on third parties to run the service, including our authentication
provider (Clerk) and our hosting/infrastructure providers. Each processes data
only as needed to deliver their part of the service.

## Your rights

Depending on your jurisdiction you may have rights to access, correct, export,
or delete your personal data. Contact **barak3656@gmail.com** to exercise them.

## Changes

We may update this policy; material changes will be reflected by the "Last
updated" date above.
