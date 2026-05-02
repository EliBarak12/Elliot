# 042 — Dashboard + Sources Page

**Sprint**: 4 | **Estimate**: 4h | **Depends on**: 041

## Objective
First two real pages: overview dashboard and source management UI.

## Files to Create

### `src/pages/Dashboard.tsx`
- 4 stat cards: Sources, Tools, Skills, Connector Status — data from `useSessionState()`
- Getting-started checklist: "Add a source", "Create a tool", "Build connector" (ticked when done)
- Recent audit log feed: last 10 entries via `callTool('studio_get_audit_log', { limit: 10 })`
- Quick-action buttons linking to `/sources`, `/tools`, `/connector`

### `src/pages/SourcesPage.tsx`
- Source list: name, type badge, table count, row count, last fetched
- "Add Source" button → opens `AddSourceDialog`
- Click source row → expand to show tables
- Click table → show column list with type badges
- "Profile" button → opens column stats panel
- "Refresh" button → calls `elliot_refresh_source`
- "Remove" button → confirms then calls `elliot_remove_source`

### `src/components/sources/AddSourceDialog.tsx`
- Type selector: API / File / DB
- Dynamic sub-form per type (URL + auth for API; file path for File; connection string for DB)
- On submit → calls `elliot_discover_source` → invalidates `sources` query

## Done When
- [ ] Dashboard shows correct counts when plugin has loaded sources + tools
- [ ] Adding a source via dialog calls `elliot_discover_source` and updates the list
- [ ] Removing a source updates the list immediately
