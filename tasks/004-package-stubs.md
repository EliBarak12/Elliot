# 004 — Python Package Stubs + Verify

**Sprint**: 1 | **Estimate**: 1h | **Depends on**: 003

## Objective
Create the three Python package skeletons so uv workspace linking works.

## For Each Package (`core`, `mcp-plugin`, `connector-runtime`)

### `packages/<name>/pyproject.toml`
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "elliot-<name>"        # elliot-core / elliot-mcp-plugin / elliot-connector-runtime
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []             # filled in per-package below

[tool.hatch.build.targets.wheel]
packages = ["src/elliot_<name>"]  # elliot_core / elliot_mcp_plugin / elliot_connector_runtime
```

**Per-package dependencies:**

`elliot-core`:
```toml
dependencies = [
    "pydantic>=2.7",
    "httpx>=0.27",
    "jmespath>=1.0",
    "cryptography>=42.0",
    "psycopg2-binary>=2.9",
]
```

`elliot-mcp-plugin`:
```toml
dependencies = [
    "elliot-core",
    "mcp>=1.0",
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
]
```

`elliot-connector-runtime`:
```toml
dependencies = [
    "elliot-core",
    "mcp>=1.0",
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
]
```

### `packages/<name>/src/elliot_<name>/__init__.py`
```python
"""Elliot <Name> package."""
```

### `packages/<name>/tests/__init__.py` (empty)

## Done When
- [ ] `uv sync` resolves all dependencies without conflict
- [ ] `uv run python -c "import elliot_core"` succeeds
- [ ] `uv run python -c "import elliot_mcp_plugin"` succeeds
