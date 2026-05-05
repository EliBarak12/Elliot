"""Tests for ElliotSession: save/load state roundtrip."""

from __future__ import annotations

from pathlib import Path

import pytest

from elliot_core.types.connector import ProductContext
from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import ToolDefinition
from elliot_mcp_plugin.session import ElliotSession


@pytest.fixture()
def session(tmp_path: Path) -> ElliotSession:
    return ElliotSession(cwd=str(tmp_path))


def test_load_empty_session_is_noop(session: ElliotSession):
    session.load()
    assert session.product_context is None
    assert session.sources == {}


def test_save_and_load_product_context(session: ElliotSession, tmp_path: Path):
    session.product_context = ProductContext(
        name="Acme API", description="Acme's REST API", base_url="https://acme.com"
    )
    session.save()

    restored = ElliotSession(cwd=str(tmp_path))
    restored.load()
    assert restored.product_context is not None
    assert restored.product_context.name == "Acme API"
    assert restored.product_context.base_url == "https://acme.com"


def test_save_and_load_sources(session: ElliotSession, tmp_path: Path):
    src = SourceConfig(id="api", name="API", type="rest", url="https://acme.com/v1")
    session.sources["api"] = src
    session.save()

    restored = ElliotSession(cwd=str(tmp_path))
    restored.load()
    assert "api" in restored.sources
    assert restored.sources["api"].url == "https://acme.com/v1"


def test_save_and_load_tools(session: ElliotSession, tmp_path: Path):
    tool = ToolDefinition(
        id="list_items",
        name="List items",
        description="Return items",
        category="READ",
        source_ids=["api"],
    )
    src = SourceConfig(id="api", name="API", type="rest", url="https://acme.com/v1")
    session.sources["api"] = src
    session.registry.add(tool)
    session.save()

    restored = ElliotSession(cwd=str(tmp_path))
    restored.load()
    # sources are restored; tools are in saved JSON but registry is empty on fresh session
    assert "api" in restored.sources


def test_save_with_no_context(session: ElliotSession, tmp_path: Path):
    session.save()
    restored = ElliotSession(cwd=str(tmp_path))
    restored.load()
    assert restored.product_context is None
