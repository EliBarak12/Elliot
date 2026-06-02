# Task 066 — Secrets & Credentials Management

## Goal
Replace hardcoded credentials in `connector.json` with environment variable placeholders resolved at load time. Secrets must never appear in logs, API responses, or serialized output.

## Why
Right now any string in `connector.json` (DB passwords, API keys, bearer tokens) lives in plaintext on disk. A developer checking the file into git or sharing it accidentally exposes every connected system. The fix is simple: allow `{{ env:VAR_NAME }}` placeholders that Elliot resolves from the process environment at startup — the file stays safe to commit, the secret stays in `.env`.

## File to create

### `packages/core/src/elliot_core/secrets.py`

```python
from __future__ import annotations

import os
import re
from typing import Any

_PLACEHOLDER = re.compile(r"\{\{\s*env:([A-Z0-9_]+)\s*\}\}")


class SecretResolutionError(Exception):
    """Raised when a required env var is missing."""


def resolve_secrets(obj: Any, _seen: set[str] | None = None) -> Any:
    """
    Recursively walk obj (dict / list / str) and replace every
    {{ env:VAR_NAME }} placeholder with the corresponding env var value.
    Raises SecretResolutionError for missing vars.
    """
    if isinstance(obj, str):
        def _replace(match: re.Match) -> str:
            name = match.group(1)
            val = os.environ.get(name)
            if val is None:
                raise SecretResolutionError(
                    f"Required secret '{{{{ env:{name} }}}}' is not set in environment"
                )
            return val
        return _PLACEHOLDER.sub(_replace, obj)
    if isinstance(obj, dict):
        return {k: resolve_secrets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_secrets(item) for item in obj]
    return obj


def check_secrets(obj: Any) -> list[str]:
    """
    Return a list of all {{ env:VAR_NAME }} placeholders found in obj
    whose env var is NOT currently set. Used by the linter / CLI check.
    """
    missing: list[str] = []
    _collect(obj, missing)
    return missing


def _collect(obj: Any, missing: list[str]) -> None:
    if isinstance(obj, str):
        for m in _PLACEHOLDER.finditer(obj):
            name = m.group(1)
            if os.environ.get(name) is None:
                missing.append(name)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect(v, missing)
    elif isinstance(obj, list):
        for item in obj:
            _collect(item, missing)
```

## Wire into `loader.py`

```python
from elliot_core.secrets import resolve_secrets, SecretResolutionError

def load_connector(path: str | Path) -> ConnectorConfig:
    raw = json.loads(Path(path).read_text())
    try:
        resolved = resolve_secrets(raw)
    except SecretResolutionError as exc:
        raise ConnectorLoadError(str(exc)) from exc
    return ConnectorConfig(**resolved)
```

## Linter check (add to task 061 `lint_connector`)

Add a new `LintIssue` type `SECRET_LITERAL` that fires when the linter sees a value matching:
- A URL with `://user:password@`
- A field named `api_key`, `password`, `token`, `secret` with a non-placeholder string value longer than 8 chars

```python
_SECRET_FIELDS = {"api_key", "password", "token", "secret", "key", "bearer"}
_SECRET_URL = re.compile(r"://[^@]+:[^@]+@")

def _check_secret_literals(config: ConnectorConfig) -> list[LintIssue]:
    issues = []
    for source in config.sources:
        if source.url and _SECRET_URL.search(source.url):
            issues.append(LintIssue(
                code="SECRET_IN_URL",
                severity="error",
                location=f"sources[{source.id}].url",
                message="Credentials embedded in URL. Use {{ env:VAR }} placeholder instead.",
            ))
        if source.auth:
            auth_dict = source.auth.model_dump()
            for field, val in auth_dict.items():
                if field in _SECRET_FIELDS and isinstance(val, str) and len(val) > 8:
                    if not val.startswith("{{"):
                        issues.append(LintIssue(
                            code="SECRET_LITERAL",
                            severity="error",
                            location=f"sources[{source.id}].auth.{field}",
                            message=f"Literal secret in '{field}'. Use {{ env:VAR }} placeholder instead.",
                        ))
    return issues
```

## CLI command

Add `elliot secrets check <connector.json>` to `elliot_core/cli.py`:

```python
# elliot secrets check my-api.connector.json
# Exit 0 if all placeholders resolve, exit 1 + list missing vars if not.

import click
from elliot_core.secrets import check_secrets

@cli.command("check")
@click.argument("connector_path")
def secrets_check(connector_path: str):
    import json
    raw = json.loads(Path(connector_path).read_text())
    missing = check_secrets(raw)
    if missing:
        click.echo(f"Missing env vars ({len(missing)}):")
        for name in missing:
            click.echo(f"  - {name}")
        raise SystemExit(1)
    click.echo("All secrets resolved.")
```

## Example connector.json

```json
{
  "sources": [{
    "id": "my_db",
    "type": "postgres",
    "url": "postgresql://{{ env:DB_USER }}:{{ env:DB_PASS }}@localhost:5432/mydb"
  }]
}
```

Paired `.env`:
```
DB_USER=myapp
DB_PASS=supersecret
```

## What must NOT happen
- Resolved secrets must never appear in `structlog` output (the loader should log `"secrets resolved: 3 placeholders"` not the values)
- `GET /v1/connector` (if it exists) must return the raw unresolved JSON, not the resolved one
- `SecretResolutionError` maps to HTTP 500 with message `"connector credential error — check server logs"` (no secret in response)

## Tests

```python
def test_resolve_secrets_replaces_placeholder(monkeypatch):
    monkeypatch.setenv("MY_KEY", "abc123")
    result = resolve_secrets({"auth": {"api_key": "{{ env:MY_KEY }}"}})
    assert result["auth"]["api_key"] == "abc123"

def test_resolve_secrets_raises_on_missing():
    with pytest.raises(SecretResolutionError, match="MY_MISSING"):
        resolve_secrets("{{ env:MY_MISSING }}")

def test_check_secrets_returns_missing(monkeypatch):
    monkeypatch.delenv("GONE", raising=False)
    missing = check_secrets({"url": "{{ env:GONE }}"})
    assert "GONE" in missing
```

## Estimate
3–4 hours
