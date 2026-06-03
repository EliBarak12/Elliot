# 002 — TypeScript + Vitest Config

**Sprint**: 1 | **Estimate**: 1h | **Depends on**: 001

## Objective
Shared TypeScript compiler config and Vitest workspace config used by all packages.

## Files to Create
- `tsconfig.base.json` — strict, ES2022, bundler moduleResolution, declaration, declarationMap, sourceMap, skipLibCheck. See DEVELOPMENT_GUIDE.md §2.2.
- `vitest.workspace.ts` — `defineWorkspace([...])` pointing to all 4 package vitest configs (they will be created in task 004).

## Done When
- [ ] `pnpm typecheck` exits 0 (nothing to check yet, but command recognized)
- [ ] `pnpm test` exits 0 (no tests yet)
