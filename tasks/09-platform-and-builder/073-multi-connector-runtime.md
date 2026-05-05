# Task 073 — Multi-Connector Runtime (Directory Mode)

## Goal
Allow `elliot-connector-runtime` to load **all** `*.connector.json` files from a directory instead of a single file. Each connector's tools are namespaced by its slug. One runtime process serves all connectors.

## Why
Right now if a user has a `pets.connector.json` and a `users.connector.json`, they run two runtime processes on two different ports and manage two sets of env vars. A directory mode collapses this to one process, one port, one observation DB.

## Config

| Variable | Behaviour |
|---|---|
| `ELLIOT_CONNECTOR` (existing) | Load single connector (current behaviour, unchanged) |
| `ELLIOT_CONNECTORS_DIR` (new) | Load all `*.connector.json` from this directory |

If both are set, `ELLIOT_CONNECTOR` wins.

## Tool namespacing

With one connector, tool IDs are bare: `list_animals`, `get_animal`.

With multiple connectors, tool IDs are prefixed by connector slug:
`pets__list_animals`, `pets__get_animal`, `users__get_user`.

The double-underscore separator is readable and unlikely to appear in natural tool names.

## File to update

### `packages/connector-runtime/src/elliot_connector_runtime/loader.py`

```python
def load_connectors_dir(directory: str | Path) -> dict[str, ConnectorConfig]:
    """
    Load all *.connector.json files in directory.
    Returns {slug: ConnectorConfig}.
    """
    configs = {}
    for path in Path(directory).glob("*.connector.json"):
        try:
            config = load_connector(path)
            configs[config.slug] = config
        except ConnectorLoadError as e:
            logger.warning("skipped connector", path=str(path), error=str(e))
    if not configs:
        raise ConnectorLoadError(f"No valid connectors found in {directory}")
    return configs
```

### `packages/connector-runtime/src/elliot_connector_runtime/server.py`

```python
import os
from .loader import load_connector, load_connectors_dir

connector_env = os.environ.get("ELLIOT_CONNECTOR")
dir_env = os.environ.get("ELLIOT_CONNECTORS_DIR")

if connector_env:
    configs = {None: load_connector(connector_env)}  # single mode, no prefix
elif dir_env:
    configs = load_connectors_dir(dir_env)
else:
    raise RuntimeError("Set ELLIOT_CONNECTOR or ELLIOT_CONNECTORS_DIR")

# Build namespaced tool registry
for slug, config in configs.items():
    prefix = f"{slug}__" if slug else ""
    for tool in config.tools:
        namespaced_id = f"{prefix}{tool.id}"
        registry.register(namespaced_id, tool, config)
```

## New REST endpoints

```python
@app.get("/v1/connectors")
async def list_connectors() -> list[dict]:
    return [
        {"slug": slug, "name": cfg.name, "tools": len(cfg.tools)}
        for slug, cfg in configs.items()
    ]
```

## Tests

```python
def test_load_directory(tmp_path):
    # write two connector files to tmp_path
    ...
    configs = load_connectors_dir(tmp_path)
    assert len(configs) == 2
    assert "pets" in configs
    assert "users" in configs

def test_skips_invalid(tmp_path, caplog):
    (tmp_path / "bad.connector.json").write_text("{not valid}")
    configs = load_connectors_dir(tmp_path)  # should not raise
    assert "bad" not in configs
```

## Estimate
5–7 hours
