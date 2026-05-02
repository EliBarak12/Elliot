# 027 — Auto-Registration Script

**Sprint**: 2 | **Estimate**: 1h | **Depends on**: 026

## Objective
One-command setup that registers Elliot with Claude Code and Codex — no manual JSON editing.

## Files to Create

### `packages/mcp-plugin/scripts/install.mjs`

See DEVELOPMENT_GUIDE.md §4.4 for complete implementation. What it does:
1. Write/merge `.mcp.json` at project root → `{ mcpServers: { elliot: { type: 'http', url: 'http://localhost:3000/mcp' } } }`
2. Run `claude mcp add-json elliot '...' --scope user` (fails gracefully if `claude` CLI absent)
3. Write/append `.codex/config.toml` at project root → `[mcp_servers.elliot]\nurl = "..."`
4. Write/append `~/.codex/config.toml` for user-level Codex registration (fails gracefully)
5. Print clear success/skip messages for each step

Note: `.mcp.json` and `.codex/config.toml` already exist in the repo root (created in earlier commit) — the script updates them idempotently.

## Done When
- [ ] `node scripts/install.mjs` exits 0
- [ ] `.mcp.json` contains `elliot` entry
- [ ] `.codex/config.toml` contains `[mcp_servers.elliot]`
- [ ] Running script twice doesn't duplicate entries
