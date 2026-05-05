# 001 — Root Workspace

**Sprint**: 1 | **Estimate**: 1h | **Depends on**: —

## Objective
Initialize the mixed monorepo: uv workspace for Python packages, pnpm workspace for Studio.

## Files to Create

### `pyproject.toml` (uv workspace root)
```toml
[tool.uv.workspace]
members = [
    "packages/core",
    "packages/mcp-plugin",
    "packages/connector-runtime",
]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
    "ruff>=0.4",
    "mypy>=1.10",
    "respx>=0.21",
]
```

### `.python-version`
```
3.13
```

### `pnpm-workspace.yaml` (Studio only)
```yaml
packages:
  - 'packages/studio'
```

### `Makefile`
```makefile
dev:
	honcho start

setup:
	uv run python packages/mcp-plugin/scripts/install.py

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy packages/

build-studio:
	pnpm --filter @elliot/studio run build
```

### `Procfile` (for honcho)
```
plugin: uv run uvicorn elliot_mcp_plugin.main:app --port 3000 --reload --app-dir packages/mcp-plugin/src
studio: pnpm --filter @elliot/studio run dev
```

### `.gitignore`
```
__pycache__/
*.pyc
.venv/
dist/
build/
.elliot/secrets.enc
*.connector.json
.env
coverage/
node_modules/
.ruff_cache/
.mypy_cache/
```

## Done When
- [ ] `uv sync` installs all Python dev dependencies
- [ ] `make test` recognized (no packages yet, exits 0)
- [ ] `uv run python --version` prints `Python 3.13.x`
