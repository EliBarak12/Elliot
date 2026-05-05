# Elliot — Data Flow Diagrams

## 1. Tool Call: End-to-End (Claude Code → Result)

The high-level flow for a tool call:

1. Developer asks Claude Code a question
2. Claude Code sends MCP tools/call to Plugin :3000
3. Plugin checks ConnectorCache (TTL 30s + mtime)
4. ToolExecutor fetches live data from source (REST/DB/file)
5. Data ingested into in-memory SQLite
6. SQL query runs against SQLite
7. AuditLog records result
8. Rows returned to Claude Code

## 2. Connector Load & Cache

The cache invalidates on:
- TTL expiry (default 30s)
- File mtime change

## 3. Error Handling

All `ElliotError` subclasses map to structured HTTP JSON responses via error middleware. Generic exceptions return HTTP 500 with a sanitized message.
