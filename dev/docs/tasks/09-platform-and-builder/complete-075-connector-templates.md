# Task 075 — Connector Starter Templates

## Goal
Ship a `templates/` directory with ready-to-copy `*.connector.json` files covering the four most common integration patterns. Add a `elliot init` CLI command that copies a template to the current directory and opens it for editing.

## Templates to ship

### `templates/rest-api-key.connector.json`
REST API authenticated with an API key in a header. 3 generic read tools: `list_items`, `get_item`, `search_items`. Placeholders for base URL and API key env var.

### `templates/postgres-readonly.connector.json`
PostgreSQL source. 3 read tools with parameterized queries: `list_records`, `get_record_by_id`, `search_records`. Uses `{{ env:DB_URL }}` for the connection string.

### `templates/paginated-rest.connector.json`
REST API with cursor/offset pagination. Shows the correct pattern for a `limit` + `offset` parameter pair, and a `next_cursor` field in the response.

### `templates/openapi-petstore.connector.json`
Fully filled-in example using the Swagger Petstore v3. Shows real descriptions, real SQL, real parameters. Used in docs and tutorials.

## CLI command

```bash
# List available templates
elliot init --list
# rest-api-key       — REST API with API key auth
# postgres-readonly  — PostgreSQL read-only connector
# paginated-rest     — REST API with pagination
# openapi-petstore   — Full Petstore example

# Create from template
elliot init --template rest-api-key my-api.connector.json
# Copied template to my-api.connector.json
# Edit the file and run: elliot lint my-api.connector.json
```

## Implementation

```python
# elliot_core/cli.py — add to existing CLI

@cli.command("init")
@click.option("--template", default=None, help="Template name")
@click.option("--list", "list_templates", is_flag=True)
@click.argument("output", required=False)
def init(template, list_templates, output):
    templates_dir = Path(__file__).parent / "templates"
    if list_templates:
        for f in sorted(templates_dir.glob("*.connector.json")):
            name = f.stem.replace(".connector", "")
            click.echo(f"  {name}")
        return
    if not template:
        raise click.UsageError("Provide --template or --list")
    src = templates_dir / f"{template}.connector.json"
    if not src.exists():
        raise click.UsageError(f"Unknown template '{template}'. Run: elliot init --list")
    dest = Path(output or f"{template}.connector.json")
    dest.write_text(src.read_text())
    click.echo(f"Created {dest}")
    click.echo(f"Next: elliot lint {dest}")
```

## Estimate
2–3 hours
