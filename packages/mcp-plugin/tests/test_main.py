"""Tests for the FastAPI HTTP server entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


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
