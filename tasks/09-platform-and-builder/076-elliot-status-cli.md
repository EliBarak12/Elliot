# Task 076 — `elliot status` CLI

## Goal
Add `elliot status` to the CLI. One command shows whether all Elliot services are running, what connector is loaded, how many tools are live, and whether the observation DB is reachable.

## Why
Right now you have to open a browser and click around the Studio to find out if services are running. During development or on a server this wastes time. `elliot status` gives you a one-line answer.

## Output

```
$ elliot status

Elliot Services
────────────────────────────────────────────────
  plugin     http://localhost:3000  ✓ running   3 connectors
  runtime    http://localhost:3001  ✓ running   ecommerce (4 tools)
  studio     http://localhost:5173  ✓ running
  database   sqlite:///.elliot/observations.db  ✓ connected  1,243 tool calls

  All services healthy.

# Or when something is down:
  plugin     http://localhost:3000  ✗ not reachable
  runtime    http://localhost:3001  ✓ running   ecommerce (4 tools)
  studio     http://localhost:5173  ✗ not reachable
  database   sqlite:///.elliot/observations.db  ✓ connected

  2 services not reachable. Is honcho running? Try: honcho start
```

## Implementation

Add to `elliot_core/cli.py`:

```python
import os
import httpx
import click

PLUGIN_URL  = os.environ.get("ELLIOT_PLUGIN_URL",  "http://localhost:3000")
RUNTIME_URL = os.environ.get("ELLIOT_RUNTIME_URL", "http://localhost:3001")
STUDIO_URL  = os.environ.get("ELLIOT_STUDIO_URL",  "http://localhost:5173")
DB_URL      = os.environ.get("ELLIOT_DB_URL", "sqlite:///.elliot/observations.db")

@cli.command("status")
def status():
    """Show running status of all Elliot services."""
    results = []

    for name, url, detail_path in [
        ("plugin",  PLUGIN_URL,  "/v1/health"),
        ("runtime", RUNTIME_URL, "/v1/health"),
        ("studio",  STUDIO_URL,  None),
    ]:
        try:
            path = detail_path or "/"
            r = httpx.get(f"{url}{path}", timeout=3)
            detail = ""
            if r.status_code == 200 and detail_path:
                data = r.json()
                if name == "plugin":
                    detail = f"{data.get('connector_count', 0)} connectors"
                elif name == "runtime":
                    slug = data.get("connector", {}).get("slug", "")
                    tools = data.get("connector", {}).get("tool_count", 0)
                    detail = f"{slug} ({tools} tools)" if slug else ""
            results.append((name, url, True, detail))
        except Exception:
            results.append((name, url, False, ""))

    # DB check
    try:
        from elliot_core.observation_store import ObservationStore
        store = ObservationStore(DB_URL)
        count = store.recent_tool_calls(1)  # just pings the DB
        results.append(("database", DB_URL, True, ""))
    except Exception:
        results.append(("database", DB_URL, False, ""))

    click.echo("\nElliot Services")
    click.echo("─" * 48)
    all_ok = True
    for name, url, ok, detail in results:
        icon = "✓" if ok else "✗"
        detail_str = f"  {detail}" if detail else ""
        click.echo(f"  {name:<10} {url:<35} {icon} {'running' if ok else 'not reachable'}{detail_str}")
        if not ok:
            all_ok = False

    click.echo()
    if all_ok:
        click.echo("  All services healthy.")
    else:
        failed = sum(1 for _, _, ok, _ in results if not ok)
        click.echo(f"  {failed} service(s) not reachable. Is honcho running? Try: honcho start")
        raise SystemExit(1)
```

## Tests

```python
def test_status_all_down(monkeypatch, runner):
    # mock httpx to raise ConnectionError
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 1
    assert "not reachable" in result.output

def test_status_all_up(monkeypatch, runner):
    # mock httpx to return 200 with valid health JSON
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0
    assert "All services healthy" in result.output
```

## Estimate
2–3 hours
