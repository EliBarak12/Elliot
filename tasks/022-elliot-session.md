# 022 — ElliotSession

**Sprint**: 2 | **Estimate**: 3h | **Depends on**: 021

## Objective
Singleton session object that holds all live state for the MCP plugin. Persists to `.elliot/` workspace directory.

## Files to Create

### `packages/mcp-plugin/src/session.ts`
**Class `ElliotSession`:**
- Properties: `sqliteEngine: SQLiteEngine`, `toolRegistry: ToolRegistry`, `connectorBuilder: ConnectorBuilder`, `workspace: WorkspaceStore`, `sources: Map<string, SourceConfig>`, `productContext?: ProductContext`, `runtimeProcess?: ChildProcess`
- `load(): Promise<void>` — read `.elliot/session.json`; restore sources, tools, skills, productContext
- `save(): Promise<void>` — write current state to `.elliot/session.json`
- Instantiated **once** at plugin server start; shared across all MCP HTTP sessions

### `packages/core/src/workspace/store.ts`
**Class `WorkspaceStore`:**
- `constructor(cwd: string)` — workspace dir is `cwd/.elliot/`
- `loadSession(): Promise<SavedSession | null>`
- `saveSession(data: SavedSession): Promise<void>`
- `loadSecrets(): Promise<Record<string, string>>` — decrypt `.elliot/secrets.enc` with AES-256-GCM (key derived from machine ID or env `ELLIOT_SECRET_KEY`)
- `saveSecrets(secrets: Record<string, string>): Promise<void>` — encrypt + write
- `ensureGitignore(): Promise<void>` — append `.elliot/secrets.enc` to `.gitignore` if not present

## Done When
- [ ] `save()` then `load()` restores identical state
- [ ] `secrets.enc` is binary (not plaintext JSON)
- [ ] `.gitignore` updated on first `saveSecrets` call
