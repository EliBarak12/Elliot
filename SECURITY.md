# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities **privately** — do not open a public
issue or pull request for a suspected vulnerability.

- Preferred: open a [private vulnerability report](https://github.com/EliBarak12/Elliot/security/advisories/new)
  via GitHub Security Advisories.
- Alternatively, email **support@elliot-cloud.com** with the details and a way to
  reach you.

Please include, where possible:

- the affected component (`elliot-core`, `elliot-mcp-plugin`,
  `elliot-connector-runtime`, or `elliot-studio`) and version/commit,
- a description of the issue and its impact,
- reproduction steps or a proof of concept.

We aim to acknowledge a report within 3 business days and to provide a
remediation timeline after triage. Please give us a reasonable window to ship a
fix before any public disclosure.

## Supported versions

Elliot is pre-1.0; security fixes land on `main`. Pin to a released tag and
upgrade promptly when a security release is published.

## Scope notes for connector authors

Elliot executes tools that talk to **author-supplied** APIs and databases.
Connector files are designed to be safe to commit — secrets are referenced as
`{{ env:NAME }}` and resolved at runtime, never stored in the connector JSON.
Outbound REST fetches are SSRF-guarded (private, loopback, and cloud-metadata
hosts are blocked) and tool SQL is validated read-only. If you find a way
around any of these boundaries, please report it as above.
