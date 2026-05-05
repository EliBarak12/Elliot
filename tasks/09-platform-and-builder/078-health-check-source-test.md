# Task 078 — Health Check & Source Connection Test

## Goal
Add two capabilities to both services:
1. `GET /v1/health` — detailed health endpoint showing connector status, source reachability, and DB connectivity
2. `test_source_connection` builder tool (via task 071) — lets the agent verify a source is reachable before saving the connector

## Why
`/healthz` only tells you the process is running. It doesn’t tell you whether the connector loaded, whether each source is reachable, or whether the observation DB is connected. Without this you find out something is broken when the first tool call fails.

## `/v1/health` Response

```json
{
  "status": "healthy",
  "connector": {
    "slug": "ecommerce",
    "name": "E-commerce Domain",
    "version": "1.0.0",
    "tool_count": 4,
    "source_count": 3
  },
  "sources": [
    {"id": "products_api", "type": "rest",     "status": "ok",    "latency_ms": 142},
    {"id": "inventory_db", "type": "postgres", "status": "ok",    "latency_ms": 8},
    {"id": "categories",   "type": "file",     "status": "ok",    "latency_ms": 1}
  ],
  "observation_db": {"status": "ok", "tool_calls_total": 1243},
  "uptime_seconds": 3720
}
```

If any source is unreachable, `status` becomes `"degraded"` and the HTTP status is still 200 (so load balancers don’t kill the pod — the connector may still serve tools from other sources).

## Implementation in `server.py`

```python
import asyncio
import time

_start_time = time.time()

@app.get("/v1/health")
async def health():
    source_results = await asyncio.gather(
        *[_check_source(s) for s in config.sources],
        return_exceptions=True,
    )
    sources_out = []
    all_ok = True
    for source, result in zip(config.sources, source_results):
        if isinstance(result, Exception):
            sources_out.append({"id": source.id, "type": source.type,
                                 "status": "error", "error": str(result)})
            all_ok = False
        else:
            sources_out.append({"id": source.id, "type": source.type,
                                 "status": "ok", "latency_ms": result})

    db_status = "ok"
    db_count = 0
    try:
        calls = store.recent_tool_calls(1)
        db_count = len(store.recent_tool_calls(10000))  # rough total
    except Exception:
        db_status = "error"
        all_ok = False

    return {
        "status": "healthy" if all_ok else "degraded",
        "connector": {
            "slug": config.slug, "name": config.name,
            "version": config.version,
            "tool_count": len(config.tools),
            "source_count": len(config.sources),
        },
        "sources": sources_out,
        "observation_db": {"status": db_status, "tool_calls_total": db_count},
        "uptime_seconds": int(time.time() - _start_time),
    }

async def _check_source(source) -> float:
    """Ping a source and return latency_ms. Raises on failure."""
    t0 = time.monotonic()
    fetcher = fetcher_factory(source)
    await fetcher.ping()   # lightweight check: HEAD for REST, SELECT 1 for DB, stat() for file
    return round((time.monotonic() - t0) * 1000, 1)
```

## `test_source_connection` builder tool

Add to `builder_tools.py` (task 071):

```python
def test_source_connection(source_config_json: str) -> dict:
    """
    Test whether a source configuration is reachable before saving the connector.
    Pass a SourceConfig JSON object. Returns {ok: bool, latency_ms: float, error: str|None}.
    Use this after the user provides connection details to confirm they work.
    """
    import asyncio
    from elliot_core.types.source import SourceConfig
    try:
        source = SourceConfig(**json.loads(source_config_json))
        fetcher = fetcher_factory(source)
        t0 = time.monotonic()
        asyncio.run(fetcher.ping())
        ms = round((time.monotonic() - t0) * 1000, 1)
        return {"ok": True, "latency_ms": ms, "error": None}
    except Exception as exc:
        return {"ok": False, "latency_ms": None, "error": str(exc)}
```

## Tests

```python
def test_health_all_ok(client, mock_sources_up):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
    assert all(s["status"] == "ok" for s in r.json()["sources"])

def test_health_degraded_when_source_down(client, mock_one_source_down):
    r = client.get("/v1/health")
    assert r.status_code == 200  # still 200 — process is alive
    assert r.json()["status"] == "degraded"
```

## Estimate
3–4 hours
