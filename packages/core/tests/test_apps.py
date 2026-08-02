"""Tests for elliot_core.apps — ui:// template building and the Apps extension."""

from __future__ import annotations

import json
import re
from pathlib import Path

from elliot_core.apps.template_builder import (
    build_apps_extension,
    build_tool_app_html,
    inline_custom_html,
    tool_ui_meta,
    ui_resource_uri,
)
from elliot_core.types import ConnectorBranding, ConnectorConfig, ToolDefinition, ToolUIConfig
from elliot_core.types.source import SourceConfig


def _tool(**ui_kwargs: object) -> ToolDefinition:
    return ToolDefinition(
        id="list_orders",
        name="List orders",
        description="List the orders",
        category="READ",
        source_ids=["s"],
        sql="SELECT * FROM orders",
        ui=ToolUIConfig(**ui_kwargs),  # type: ignore[arg-type]
    )


def _connector(tool: ToolDefinition) -> ConnectorConfig:
    return ConnectorConfig(
        name="Shop",
        slug="shop",
        version="1.0.0",
        sources=[SourceConfig(id="s", name="s", type="file", url="x")],
        tools=[tool],
        skills=[],
    )


class TestUris:
    def test_uri_shape(self) -> None:
        assert ui_resource_uri("shop", "list_orders") == "ui://shop/list_orders"

    def test_uri_without_slug(self) -> None:
        assert ui_resource_uri(None, "t") == "ui://connector/t"


class TestToolMeta:
    def test_default_visibility_is_omitted(self) -> None:
        meta = tool_ui_meta(ToolUIConfig(), "ui://shop/list_orders")
        assert meta == {"ui": {"resourceUri": "ui://shop/list_orders"}}

    def test_narrowed_visibility_is_stamped(self) -> None:
        meta = tool_ui_meta(ToolUIConfig(visibility=["app"]), "ui://shop/t")
        assert meta["ui"]["visibility"] == ["app"]


class TestTemplateBuilding:
    def test_preset_shell_gets_tool_config_injected(self) -> None:
        tool = _tool(preset="table", mapping={"columns": "id,total"})
        html = build_tool_app_html(tool, tool.ui, connector_slug="shop")  # type: ignore[arg-type]
        match = re.search(
            r'<script type="application/json" id="elliot-ui-config">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert match, "config script tag missing from built template"
        config = json.loads(match.group(1))
        assert config["tool_id"] == "list_orders"
        assert config["preset"] == "table"
        assert config["mapping"] == {"columns": "id,total"}
        assert config["title"] == "List orders"

    def test_chart_preset_passes_through(self) -> None:
        tool = _tool(preset="chart", mapping={"x": "customer", "y": "total"})
        html = build_tool_app_html(tool, tool.ui, connector_slug="shop")  # type: ignore[arg-type]
        match = re.search(
            r'<script type="application/json" id="elliot-ui-config">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert match
        config = json.loads(match.group(1))
        assert config["preset"] == "chart"
        assert config["mapping"] == {"x": "customer", "y": "total"}

    def test_config_json_cannot_break_out_of_script_tag(self) -> None:
        tool = _tool(preset="table", title="</script><script>alert(1)</script>")
        html = build_tool_app_html(tool, tool.ui, connector_slug="shop")  # type: ignore[arg-type]
        # The injected payload escapes "</" so the tag cannot close early.
        assert "</script><script>alert(1)" not in html

    def test_custom_html_file_is_served(self, tmp_path: Path) -> None:
        (tmp_path / "view.html").write_text("<html><body>custom!</body></html>")
        tool = _tool(preset="custom", custom_html="view.html")
        html = build_tool_app_html(tool, tool.ui, connector_dir=tmp_path)  # type: ignore[arg-type]
        assert html == "<html><body>custom!</body></html>"

    def test_custom_html_outside_connector_dir_degrades_to_preset(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (tmp_path / "secret.html").write_text("<html>secret</html>")
        tool = _tool(preset="custom", custom_html="../secret.html")
        html = build_tool_app_html(tool, tool.ui, connector_dir=outside)  # type: ignore[arg-type]
        assert "secret" not in html
        assert "elliot-ui-config" in html  # fell back to the preset shell


class TestAppsExtension:
    def test_no_ui_tools_means_no_extension(self) -> None:
        tool = ToolDefinition(
            id="t", name="T", description="d", category="READ", source_ids=["s"], sql="SELECT 1"
        )
        assert build_apps_extension(_connector(tool)) is None

    def test_disabled_ui_is_skipped(self) -> None:
        tool = _tool(enabled=False)
        assert build_apps_extension(_connector(tool)) is None

    def test_extension_carries_resource_with_csp(self) -> None:
        tool = _tool(preset="table", csp_connect_domains=["https://api.shop.example"])
        ext = build_apps_extension(_connector(tool))
        assert ext is not None
        resources = list(ext.resources())
        assert len(resources) == 1
        resource = resources[0].resource
        assert str(resource.uri) == "ui://shop/list_orders"
        assert resource.mime_type == "text/html;profile=mcp-app"
        assert resource.meta is not None
        assert resource.meta["ui"]["csp"]["connectDomains"] == ["https://api.shop.example"]
        assert resource.meta["ui"]["prefersBorder"] is True


class TestBranding:
    def test_branding_is_injected_into_view_config(self) -> None:
        tool = _tool(preset="table")
        branding = ConnectorBranding(
            accent="#c02434", accent_dark="#ff6b7a", logo="data:image/svg+xml;base64,PHN2Zz4="
        )
        html = build_tool_app_html(tool, tool.ui, connector_slug="shop", branding=branding)  # type: ignore[arg-type]
        match = re.search(
            r'<script type="application/json" id="elliot-ui-config">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert match
        config = json.loads(match.group(1))
        assert config["branding"] == {
            "accent": "#c02434",
            "accent_dark": "#ff6b7a",
            "logo": "data:image/svg+xml;base64,PHN2Zz4=",
        }

    def test_no_branding_means_no_config_key(self) -> None:
        tool = _tool(preset="table")
        html = build_tool_app_html(tool, tool.ui, connector_slug="shop")  # type: ignore[arg-type]
        match = re.search(
            r'<script type="application/json" id="elliot-ui-config">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert match
        assert "branding" not in json.loads(match.group(1))

    def test_empty_branding_is_not_injected(self) -> None:
        tool = _tool(preset="table")
        html = build_tool_app_html(
            tool,
            tool.ui,  # type: ignore[arg-type]
            branding=ConnectorBranding(),
        )
        match = re.search(
            r'<script type="application/json" id="elliot-ui-config">(.*?)</script>',
            html,
            re.DOTALL,
        )
        assert match
        assert "branding" not in json.loads(match.group(1))

    def test_https_logo_origin_declared_in_resource_csp(self) -> None:
        tool = _tool(preset="table")
        cfg = _connector(tool).model_copy(
            update={
                "branding": ConnectorBranding(
                    accent="#123456", logo="https://cdn.shop.example/img/logo.png"
                )
            }
        )
        ext = build_apps_extension(cfg)
        assert ext is not None
        resource = next(iter(ext.resources())).resource
        assert resource.meta is not None
        assert resource.meta["ui"]["csp"]["resourceDomains"] == ["https://cdn.shop.example"]

    def test_data_logo_needs_no_resource_domains(self) -> None:
        tool = _tool(preset="table")
        cfg = _connector(tool).model_copy(
            update={"branding": ConnectorBranding(logo="data:image/png;base64,AAAA")}
        )
        ext = build_apps_extension(cfg)
        assert ext is not None
        resource = next(iter(ext.resources())).resource
        # No connect domains and a data: logo → no CSP block at all.
        assert resource.meta is None or "csp" not in resource.meta.get("ui", {})

    def test_accent_validation_rejects_non_hex(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="hex color"):
            ConnectorBranding(accent="red")

    def test_logo_validation_rejects_http_and_javascript(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="data:image"):
            ConnectorBranding(logo="http://insecure.example/logo.png")
        with pytest.raises(ValueError, match="data:image"):
            ConnectorBranding(logo="javascript:alert(1)")

    def test_short_hex_accepted(self) -> None:
        assert ConnectorBranding(accent="#f00").accent == "#f00"


class TestExportInlining:
    def test_path_is_swapped_for_contents(self, tmp_path: Path) -> None:
        (tmp_path / "view.html").write_text("<html>v</html>")
        tool = _tool(preset="custom", custom_html="view.html")
        cfg = _connector(tool)
        out = inline_custom_html(cfg, tmp_path)
        assert out.tools[0].ui is not None
        assert out.tools[0].ui.custom_html == "<html>v</html>"
        # Original config untouched.
        assert cfg.tools[0].ui is not None
        assert cfg.tools[0].ui.custom_html == "view.html"

    def test_inline_html_passes_through(self, tmp_path: Path) -> None:
        tool = _tool(preset="custom", custom_html="<html>already inline</html>")
        cfg = _connector(tool)
        assert inline_custom_html(cfg, tmp_path) is cfg

    def test_round_trips_through_serializer(self, tmp_path: Path) -> None:
        from elliot_core.connector.serializer import (
            deserialize_connector,
            serialize_connector,
        )

        tool = _tool(preset="table", mapping={"columns": "id"})
        cfg = _connector(tool)
        restored = deserialize_connector(serialize_connector(cfg))
        assert restored.tools[0].ui is not None
        assert restored.tools[0].ui.preset == "table"
