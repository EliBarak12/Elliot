# Deployment

Elliot ships as a Docker Compose stack and as honcho-managed processes for local dev.

## Local dev

```bash
make dev
```

`make dev` runs `elliot connect` (registers with every detected agent) and then `honcho start`, which boots all three services from the `Procfile`. Logs are interleaved into one terminal. Hit `Ctrl+C` to stop everything.

## Docker Compose

```bash
docker compose up --build
```

The `docker-compose.yml` defines three services — `mcp-plugin`, `runtime`, `studio` — sharing a named volume for the audit log and the connector directory.

| Service | Port | Image base |
|---|---|---|
| `elliot-mcp-plugin` | 3000 | `python:3.13-slim` |
| `elliot-connector-runtime` | 3001 | `python:3.13-slim` |
| `elliot-studio` | 5173 | nginx (built from Vite output) |

## Env vars

Every env var Elliot reads is documented in `.env.example` at the repo root. Common ones:

| Var | Purpose |
|---|---|
| `ELLIOT_CONNECTOR_DIR` | Where connector files live (default `./connectors`) |
| `ELLIOT_AUDIT_LOG` | Path to NDJSON audit log |
| `ELLIOT_LOG_LEVEL` | `debug` / `info` / `warning` |
| `<YOUR_SOURCE>_API_KEY` | Per-source secrets referenced by connector files |

## Hosting

The plugin + runtime can run anywhere a Python service runs (Fly.io, Render, Railway, Cloud Run, plain VM). Studio is static — drop the Vite build into any static host (Vercel, Netlify, S3+CloudFront, GitHub Pages).

For a single-host deploy, the Compose file is enough. For multi-host, split:

- Plugin behind your auth proxy, public-ish
- Runtime on a private network — agents never call it directly
- Studio on a static host with CORS pointed at the plugin

## Observability

The audit log is the spine. Tail it, ship it to Loki/Datadog/ELK, alert on `error` lines, dashboard on `duration_ms`. Every line is one JSON object, one tool call.

```bash
tail -F audit.log | jq 'select(.error != null)'
```
