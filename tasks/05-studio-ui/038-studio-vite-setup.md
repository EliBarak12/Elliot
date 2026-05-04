# 038 — Studio Vite + shadcn + Tailwind Setup

**Sprint**: 4 | **Estimate**: 2h | **Depends on**: 004

## Objective
Bootstrap the Studio React 19 app with all UI dependencies installed and shadcn initialized.

## Steps
```bash
cd packages/studio
npm create vite@latest . -- --template react-ts
pnpm add react@19 react-dom@19
pnpm add @tanstack/react-router @tanstack/react-query @tanstack/react-table
pnpm add zustand @modelcontextprotocol/sdk
pnpm add -D tailwindcss @tailwindcss/vite @tanstack/router-devtools @tanstack/react-query-devtools
pnpm dlx shadcn@latest init
# Choose: TypeScript, Default style, Slate base, src/components/ui, CSS variables
pnpm dlx shadcn@latest add button card input textarea select badge
pnpm dlx shadcn@latest add dialog sheet tabs table
pnpm dlx shadcn@latest add toast sonner chart
```

## Key library versions
| Library | Version |
|---------|---------|
| React | 19 |
| TanStack Router | v1 |
| TanStack Query | v5 |
| TanStack Table | v8 |
| shadcn/ui | latest (React 19 compatible) |
| Zustand | v5 |

## Files to Create / Confirm
- `packages/studio/vite.config.ts` — NO proxy, port 5173
- `packages/studio/components.json` — shadcn config
- `packages/studio/src/index.css` — Tailwind directives + shadcn CSS variables
- `packages/studio/package.json` — must include `@modelcontextprotocol/sdk` as a dep

## Usage split
- **TanStack Query** — all async server state: connector data, tool calls, session list, health status
- **TanStack Router** — type-safe file-based routing with `createRoute` / `Link` / `useRouterState`
- **TanStack Table** — tools page, sessions table, token metrics table
- **Zustand** — pure UI state only: selected tool ID, sidebar collapsed, theme preference

## Done When
- [ ] `pnpm --filter @elliot/studio run dev` starts without error
- [ ] `http://localhost:5173` renders default Vite page
- [ ] `pnpm dlx shadcn@latest add button` works (shadcn initialized)
- [ ] **No** `/api` proxy in `vite.config.ts`
