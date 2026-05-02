# 004 — Package Stubs + Verify Install

**Sprint**: 1 | **Estimate**: 1h | **Depends on**: 003

## Objective
Create the four package skeletons so workspace linking works and `pnpm install` resolves cross-package deps.

## Files to Create
For each of the 4 packages (`core`, `mcp-plugin`, `connector-runtime`, `studio`):
- `packages/<name>/package.json` — correct `name` (`@elliot/<name>`), `version: 0.1.0`, `type: module`, `exports` pointing to `./dist/index.js`. See DEVELOPMENT_GUIDE.md for each package's full `package.json`.
- `packages/<name>/tsconfig.json` — extends `../../tsconfig.base.json`, `outDir: ./dist`, `rootDir: ./src`.
- `packages/<name>/vitest.config.ts` — `defineConfig({ test: { globals: true, environment: 'node', include: [...], coverage: { thresholds: { lines: 85, functions: 85, branches: 80 } } } })`
- `packages/<name>/src/index.ts` — empty stub `export {}`

## Done When
- [ ] `pnpm install` resolves `@elliot/core` as a dep of `@elliot/mcp-plugin`
- [ ] `pnpm -r run typecheck` exits 0 across all packages
- [ ] `pnpm test` exits 0 (no tests yet)
