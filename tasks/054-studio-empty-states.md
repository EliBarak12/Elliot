# 054 — Studio Empty States + Toast Notifications

**Sprint**: 4 | **Estimate**: 2h | **Depends on**: 048

## Objective
Every page with a list must have a non-blank empty state. Every mutation must have error/success feedback.

## What to Implement

### Empty States (add to each page)
| Page | Empty State Message | CTA |
|------|--------------------|----- |
| Sources | "No sources loaded yet" | "Add your first source" button |
| Tools | "No tools defined yet" | "Create your first tool" button |
| Skills | "No skills defined yet" | "Create your first skill" button |
| Metrics | "No tool calls recorded yet" | "Open Playground to test a tool" link |
| Evaluation | "No eval suites yet" | "Create your first suite" button |
| Playground history | "No invocations yet" | "Select a tool and run it" |

### Toast notifications (use `sonner`)
Add `<Toaster />` to `AppShell`. Call `toast.success()` / `toast.error()` after:
- Source discovered successfully
- Source discovery failed
- Tool saved
- Tool save failed
- Connector built
- Runtime started
- Any MCP call that returns `isError: true`

### Network error handling
In `getMcpClient()`: if connection fails, show a persistent toast: "Cannot connect to Elliot plugin. Is it running on :3000?" with a "Retry" button.

## Done When
- [ ] No page shows a blank content area when data is empty
- [ ] Successful tool save shows a success toast
- [ ] Plugin unreachable shows a persistent error toast with retry
