# 038 — Studio Vite + shadcn + Tailwind Setup

**Sprint**: 4 | **Estimate**: 2h | **Depends on**: 004

## Objective
Bootstrap the Studio React app with all UI dependencies installed and shadcn initialized.

## Steps
```bash
cd packages/studio
npm create vite@latest . -- --template react-ts
pnpm add react-router-dom zustand @tanstack/react-query @modelcontextprotocol/sdk
pnpm add -D tailwindcss @tailwindcss/vite
pnpm dlx shadcn@latest init
# Choose: TypeScript, Default style, Slate base, src/components/ui, CSS variables
pnpm dlx shadcn@latest add button card input textarea select badge
pnpm dlx shadcn@latest add dialog sheet tabs table
pnpm dlx shadcn@latest add toast sonner chart
```

## Files to Create / Confirm
- `packages/studio/vite.config.ts` — NO proxy, port 5173. See DEVELOPMENT_GUIDE.md §6.2.
- `packages/studio/components.json` — shadcn config. See DEVELOPMENT_GUIDE.md §6.3.
- `packages/studio/src/index.css` — Tailwind directives + shadcn CSS variables
- `packages/studio/package.json` — must include `@modelcontextprotocol/sdk` as a dep

## Done When
- [ ] `pnpm --filter @elliot/studio run dev` starts without error
- [ ] `http://localhost:5173` renders default Vite page
- [ ] `pnpm dlx shadcn@latest add button` works (shadcn initialized)
- [ ] **No** `/api` proxy in `vite.config.ts`
