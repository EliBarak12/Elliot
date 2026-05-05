# Development Missions — Superseded

> **This document described the original TypeScript-based build plan (10 sequential missions).**
> It has been replaced by the task-based implementation plan in [`tasks/`](../tasks/).

## Current plan: 59 tasks across 7 epics

| Epic folder | Tasks | Focus |
|---|---|---|
| [01-monorepo-setup](../tasks/01-monorepo-setup/) | 001–004 | uv + pnpm workspace, tooling |
| [02-core-library](../tasks/02-core-library/) | 005–021 | `elliot-core` Python package |
| [03-mcp-plugin](../tasks/03-mcp-plugin/) | 022–032 | `elliot-mcp-plugin` FastMCP server :3000 |
| [04-connector-runtime](../tasks/04-connector-runtime/) | 033–037 | `elliot-connector-runtime` :3001 |
| [05-studio-ui](../tasks/05-studio-ui/) | 038–048 | React + Vite Studio dashboard |
| [06-eval-and-polish](../tasks/06-eval-and-polish/) | 049–056 | Eval, CI, error handling |
| [07-dx-and-observability](../tasks/07-dx-and-observability/) | 057–059 | Logging, error middleware, test plan |

See [`tasks/README.md`](../tasks/README.md) for the full overview.
