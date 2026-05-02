# 020 — Connector Builder + Serializer

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 016

## Objective
Assemble a validated `ConnectorConfig` from session state and serialize/deserialize it as JSON.

## Files to Create

### `packages/core/src/connector/builder.ts`
**Class `ConnectorBuilder`:**
- `setMeta(name: string, version: string, slug: string, description: string): void`
- `addSource(source: SourceConfig): void`
- `build(tools: ToolDefinition[], skills: SkillDefinition[]): ConnectorConfig` — validate full config via `ConnectorConfigSchema`, throw if invalid

### `packages/core/src/connector/serializer.ts`
- `serializeConnector(config: ConnectorConfig): string` — `JSON.stringify` with 2-space indent
- `deserializeConnector(json: string): ConnectorConfig` — parse + validate with Zod; throw `ElliotError('INVALID_CONNECTOR', ...)` if schema fails

### `packages/core/src/connector/schema-gen.ts`
- `toMcpToolSchema(tool: ToolDefinition): object` — convert `ToolDefinition.parameters` to JSON Schema object for MCP `tools/list` response
- `toOpenAiFunction(tool: ToolDefinition): object` — convert to OpenAI function-calling schema

## Done When
- [ ] `build()` → `deserializeConnector(serializeConnector(config))` produces identical output
- [ ] Invalid connector (missing required field) throws on `deserializeConnector`
- [ ] MCP JSON Schema output has correct `required` array
