# Task 072 — Connector Editor UI in Studio

## Goal
Add a `/connector` page to Elliot Studio where the user can view and edit their connector visually — without touching raw JSON. The page shows sources, tools (with inline description/SQL editing), and a live lint panel.

## Why
The feedback loop (Design → Lint → Eval → Observe → Improve) currently breaks at Improve: the user has to go back and edit JSON by hand. The Studio should close that loop. When the agent console shows "list_all has high token risk", the user should be able to click into the editor, add a LIMIT, save, and redeploy — all in one place.

## Route
`/connector` — add to React Router in `App.tsx`

## Component tree

```
ConnectorEditor
├── ConnectorHeader         (name, slug, version, save button)
├── SourcesPanel
│   ├── SourceCard[]        (id, type, url, auth hint — read only for now)
│   └── AddSourceButton     (future)
├── ToolsPanel
│   ├── ToolCard[]          (inline editable)
│   │   ├── ToolHeader      (id badge, category badge, token risk badge)
│   │   ├── DescriptionField (textarea — validates verb-first on blur)
│   │   ├── SqlField         (code editor — monospace textarea)
│   │   ├── ParameterList
│   │   │   └── ParameterRow[] (name, type, description, required toggle)
│   │   └── ToolActions     (duplicate, delete)
│   └── AddToolButton
└── LintPanel
    ├── LintSummary         (X errors, Y warnings)
    └── LintIssue[]         (severity badge, location, message, jump-to-tool link)
```

## Key behaviors

- **Auto-lint on save**: when the user clicks Save, the connector is sent to `POST /v1/connector/save` and the lint results are shown immediately in the panel.
- **Unsaved indicator**: any change marks the header with an "Unsaved" badge.
- **Token risk badge**: each tool card shows a color-coded badge (green/yellow/red) derived from the observation store's avg token estimate for that tool — or from the proposed token_risk if no observations yet.
- **Description helper**: if the description doesn't start with a verb, show a red underline and tooltip "Start with a verb: Return, List, Get, Create…"

## API endpoints needed (add to plugin server.py)

```python
@app.get("/v1/connector")
async def get_connector() -> dict:
    """Return the current connector config as JSON for the editor."""
    ...

@app.post("/v1/connector/save")
async def save_connector(body: dict) -> dict:
    """Validate, lint, and write the updated connector to disk.
    Returns {ok: bool, lint_issues: [...]}."""
    ...
```

## TypeScript interfaces

```ts
interface ConnectorEditorState {
  connector: ConnectorConfig | null;
  dirty: boolean;
  saving: boolean;
  lintIssues: LintIssue[];
}

interface LintIssue {
  code: string;
  severity: 'error' | 'warning' | 'info';
  location: string;  // e.g. "tools[list_animals].description"
  message: string;
}
```

## Estimate
10–14 hours
