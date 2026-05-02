# 001 — Root Workspace

**Sprint**: 1 | **Estimate**: 1h | **Depends on**: —

## Objective
Initialize the pnpm monorepo root: `package.json`, `pnpm-workspace.yaml`, `.gitignore`.

## Files to Create
- `package.json` — workspace root. Scripts: `dev`, `setup`, `build`, `test`, `test:watch`, `test:coverage`, `lint`, `typecheck`, `clean`. DevDeps: `concurrently ^8.2`, `typescript ^5.4`, `vitest ^1.5`, `@vitest/coverage-v8`, `@typescript-eslint/eslint-plugin ^7`, `@typescript-eslint/parser ^7`, `eslint ^9`, `prettier ^3`, `@types/node ^20`. See DEVELOPMENT_GUIDE.md §2.2 for exact content.
- `pnpm-workspace.yaml` — `packages: ['packages/*']`
- `.gitignore` — `node_modules/`, `dist/`, `.elliot/secrets.enc`, `*.connector.json`, `.env`, `coverage/`

## Done When
- [ ] `pnpm install` exits 0
- [ ] `pnpm run build` script recognized (even if no packages built yet)
