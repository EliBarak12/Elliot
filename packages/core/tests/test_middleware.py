"""Tests for auth_middleware, error_middleware, http_middleware, and logging_config."""

from __future__ import annotations

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elliot_core.auth_middleware import ApiKeyMiddleware
from elliot_core.error_middleware import register_error_handlers
from elliot_core.errors import ElliotError
from elliot_core.http_middleware import RequestLoggingMiddleware
from elliot_core.logging_config import configure_logging, get_logger


@pytest.fixture(autouse=True)
def reset_structlog():
    """Restore structlog to its default configuration after each test."""
    saved = structlog.get_config()
    yield
    structlog.reset_defaults()
    structlog.configure(**{k: v for k, v in saved.items() if k != "wrapper_class"})


# ── logging_config ────────────────────────────────────────────────────────────


def test_configure_logging_runs_without_error():
    configure_logging()


def test_get_logger_returns_logger():
    logger = get_logger("test_module")
    assert logger is not None


def test_get_logger_unnamed():
    logger = get_logger()
    assert logger is not None


# ── ApiKeyMiddleware ──────────────────────────────────────────────────────────


def _app_with_auth() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware)

    @app.get("/items")
    async def items() -> dict[str, str]:
        return {"data": "ok"}

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_auth_middleware_passes_when_no_env_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ELLIOT_API_KEY", raising=False)
    client = TestClient(_app_with_auth())
    resp = client.get("/items")
    assert resp.status_code == 200


def test_auth_middleware_allows_bypass_paths(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_API_KEY", "secret")
    client = TestClient(_app_with_auth())
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_auth_middleware_rejects_missing_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_API_KEY", "secret")
    client = TestClient(_app_with_auth())
    resp = client.get("/items")
    assert resp.status_code == 401


def test_auth_middleware_accepts_correct_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_API_KEY", "secret")
    client = TestClient(_app_with_auth())
    resp = client.get("/items", headers={"X-Elliot-Key": "secret"})
    assert resp.status_code == 200


def test_auth_middleware_rejects_wrong_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_API_KEY", "secret")
    client = TestClient(_app_with_auth())
    resp = client.get("/items", headers={"X-Elliot-Key": "wrong"})
    assert resp.status_code == 401


# ── error_middleware ──────────────────────────────────────────────────────────


def _app_with_errors() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/elliot-error")
    async def elliot_err() -> None:
        raise ElliotError("NOT_FOUND", "thing not found")

    @app.get("/generic-error")
    async def generic_err() -> None:
        raise RuntimeError("something exploded")

    @app.get("/auth-error")
    async def auth_err() -> None:
        raise ElliotError("AUTH_FAILED", "not authorized")

    return app


def test_error_middleware_elliot_error_returns_structured():
    client = TestClient(_app_with_errors(), raise_server_exceptions=False)
    resp = client.get("/elliot-error")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "NOT_FOUND"


def test_error_middleware_generic_error_returns_500():
    client = TestClient(_app_with_errors(), raise_server_exceptions=False)
    resp = client.get("/generic-error")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"


def test_error_middleware_auth_error_returns_401():
    client = TestClient(_app_with_errors(), raise_server_exceptions=False)
    resp = client.get("/auth-error")
    assert resp.status_code == 401


# ── RequestLoggingMiddleware ──────────────────────────────────────────────────


def _app_with_logging() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"pong": "ok"}

    return app


def test_logging_middleware_adds_request_id_header():
    client = TestClient(_app_with_logging())
    resp = client.get("/ping")
    assert resp.status_code == 200
    assert "X-Request-Id" in resp.headers


def test_logging_middleware_request_id_is_short_uuid():
    client = TestClient(_app_with_logging())
    resp = client.get("/ping")
    request_id = resp.headers.get("X-Request-Id", "")
    assert len(request_id) == 8
