# 033 — Runtime Loader + TTL Cache

**Sprint**: 3 | **Estimate**: 2h | **Depends on**: 021

## Objective
Load a `ConnectorConfig` from disk, decrypt secrets, and cache source data with TTL.

## Files to Create

### `packages/connector-runtime/src/loader.ts`
**`loadConnector(connectorPath: string, secretsPath: string): Promise<LoadedConnector>`**
- Read + parse `.elliot/connector.json` via `deserializeConnector()`
- Decrypt `.elliot/secrets.enc` via `WorkspaceStore.loadSecrets()`
- Reconstruct `SourceConfig.auth` credentials from decrypted secrets
- Return `{ config: ConnectorConfig, secrets: Record<string, string> }`

### `packages/connector-runtime/src/cache.ts`
**Class `SourceCache`:**
- `get(sourceId: string): unknown[] | undefined` — return data if not expired, else `undefined`
- `set(sourceId: string, data: unknown[], ttlMs: number): void`
- `invalidate(sourceId: string): void`
- `invalidateAll(): void`
- TTL values: `cache_1h` = 3600000ms, `cache_1d` = 86400000ms, `none` = 0 (never cache)

## Done When
- [ ] `loadConnector` returns valid `ConnectorConfig` from fixture file
- [ ] Cache returns data within TTL and `undefined` after TTL expires
- [ ] Expired entries do not appear in subsequent `get()` calls
