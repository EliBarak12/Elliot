"""Tests for the FastAPI HTTP server entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient


def _reload_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Reload elliot_mcp_plugin.main with ELLIOT_WORKSPACE pointing at tmp."""
    monkeypatch.setenv("ELLIOT_WORKSPACE", str(tmp_path))
    for mod in list(sys.modules):
        if "elliot_mcp_plugin.main" in mod:
            del sys.modules[mod]
    import elliot_mcp_plugin.main as main_mod

    return main_mod


def test_app_is_fastapi_instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_WORKSPACE", str(tmp_path))
    # Force re-import so the env var is picked up
    for mod in list(sys.modules):
        if "elliot_mcp_plugin.main" in mod:
            del sys.modules[mod]
    import elliot_mcp_plugin.main as main_mod

    assert isinstance(main_mod.app, FastAPI)


def test_cors_middleware_registered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_WORKSPACE", str(tmp_path))
    for mod in list(sys.modules):
        if "elliot_mcp_plugin.main" in mod:
            del sys.modules[mod]
    import elliot_mcp_plugin.main as main_mod

    middleware_types = [m.cls for m in main_mod.app.user_middleware]
    assert CORSMiddleware in middleware_types


def test_mcp_route_mounted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_WORKSPACE", str(tmp_path))
    for mod in list(sys.modules):
        if "elliot_mcp_plugin.main" in mod:
            del sys.modules[mod]
    import elliot_mcp_plugin.main as main_mod

    routes = [r.path for r in main_mod.app.routes]
    assert any("/mcp" in p for p in routes)


def test_api_key_middleware_registered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Auth middleware must be wired into the plugin so /mcp is not open."""
    from elliot_core.auth_middleware import ApiKeyMiddleware

    monkeypatch.setenv("ELLIOT_WORKSPACE", str(tmp_path))
    for mod in list(sys.modules):
        if "elliot_mcp_plugin.main" in mod:
            del sys.modules[mod]
    import elliot_mcp_plugin.main as main_mod

    middleware_types = [m.cls for m in main_mod.app.user_middleware]
    assert ApiKeyMiddleware in middleware_types


def test_healthz_returns_200_without_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """GET /healthz must succeed with no auth header and return the documented shape.

    docker-compose's healthcheck (`curl -f http://localhost:3000/healthz`) sends
    no `X-Elliot-Key`, so the route must answer 200 even when ELLIOT_API_KEY is
    set. The body must include status/service/version for Studio's monitor.
    """
    monkeypatch.setenv("ELLIOT_API_KEY", "secret-key")
    main_mod = _reload_main(tmp_path, monkeypatch)
    from elliot_mcp_plugin import __version__

    with TestClient(main_mod.app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "mcp-plugin", "version": __version__}


def test_health_returns_200_without_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """/health is an alias of /healthz — the connector-runtime serves /health,
    so studio's service monitor can probe either backend uniformly."""
    monkeypatch.setenv("ELLIOT_API_KEY", "secret-key")
    main_mod = _reload_main(tmp_path, monkeypatch)
    from elliot_mcp_plugin import __version__

    with TestClient(main_mod.app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "mcp-plugin"
    assert body["version"] == __version__


def test_healthz_no_connector_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A liveness probe must answer 200 even when the workspace has no
    connector — the docker-compose healthcheck runs against a freshly built
    container with an empty volume."""
    # tmp_path is empty -> no .elliot/connector.json, no session state.
    main_mod = _reload_main(tmp_path, monkeypatch)
    with TestClient(main_mod.app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_healthz_ignores_bogus_auth_header(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A wrong X-Elliot-Key header must still let /healthz through — the route
    is unauthenticated. If the middleware did not exempt it, a misconfigured
    proxy injecting a stale key would break the compose healthcheck."""
    monkeypatch.setenv("ELLIOT_API_KEY", "the-real-key")
    main_mod = _reload_main(tmp_path, monkeypatch)
    with TestClient(main_mod.app) as client:
        resp = client.get("/healthz", headers={"X-Elliot-Key": "totally-wrong"})
    assert resp.status_code == 200
    assert resp.json()["service"] == "mcp-plugin"


def test_auth_middleware_bypass_list_contains_health_paths():
    """Regression guard: the auth-middleware bypass set must list both
    /healthz and /health, otherwise the docker-compose healthcheck and
    Studio's monitor would 401 once ELLIOT_API_KEY is configured."""
    from elliot_core.auth_middleware import _BYPASS_PATHS

    assert "/healthz" in _BYPASS_PATHS
    assert "/health" in _BYPASS_PATHS
