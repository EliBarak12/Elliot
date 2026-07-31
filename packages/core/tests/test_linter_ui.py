"""Lint rules for MCP Apps view configs (UI_*)."""

from __future__ import annotations

from elliot_core.linter import lint_connector
from elliot_core.types import ConnectorConfig, ToolDefinition, ToolUIConfig
from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import ReturnField


def _connector(tool: ToolDefinition) -> ConnectorConfig:
    return ConnectorConfig(
        name="Shop",
        slug="shop",
        version="1.0.0",
        sources=[SourceConfig(id="s", name="s", type="file", url="x")],
        tools=[tool],
        skills=[],
    )


def _tool(ui: ToolUIConfig, **overrides: object) -> ToolDefinition:
    base: dict[str, object] = {
        "id": "list_orders",
        "name": "List orders",
        "description": "List orders placed by customers with totals.",
        "category": "READ",
        "source_ids": ["s"],
        "sql": "SELECT id, total FROM orders LIMIT 50",
        "return_fields": [ReturnField(field="id"), ReturnField(field="total")],
        "ui": ui,
    }
    base.update(overrides)
    return ToolDefinition(**base)  # type: ignore[arg-type]


def _codes(cfg: ConnectorConfig) -> set[str]:
    return {i.code for i in lint_connector(cfg)}


def test_clean_ui_config_raises_no_ui_issues() -> None:
    codes = _codes(_connector(_tool(ToolUIConfig(preset="table", mapping={"columns": "id,total"}))))
    assert not {c for c in codes if c.startswith("UI_")}


def test_mapping_unknown_field_warns() -> None:
    codes = _codes(
        _connector(_tool(ToolUIConfig(preset="table", mapping={"columns": "id,nonexistent"})))
    )
    assert "UI_MAPPING_UNKNOWN_FIELD" in codes


def test_pending_preset_warns() -> None:
    codes = _codes(_connector(_tool(ToolUIConfig(preset="form", mapping={}), category="WRITE")))
    assert "UI_PRESET_UNAVAILABLE" in codes


def test_chart_preset_is_shipped() -> None:
    codes = _codes(
        _connector(_tool(ToolUIConfig(preset="chart", mapping={"x": "id", "y": "total"})))
    )
    assert "UI_PRESET_UNAVAILABLE" not in codes


def test_form_on_read_tool_warns() -> None:
    codes = _codes(_connector(_tool(ToolUIConfig(preset="form"))))
    assert "UI_FORM_PRESET_MISUSE" in codes


def test_custom_without_template_is_an_error() -> None:
    issues = lint_connector(_connector(_tool(ToolUIConfig(preset="custom"))))
    match = [i for i in issues if i.code == "UI_CUSTOM_HTML_MISSING"]
    assert match and match[0].severity == "ERROR"


def test_oversized_inline_custom_html_is_an_error() -> None:
    big = "<html>" + "x" * (300 * 1024) + "</html>"
    codes = _codes(_connector(_tool(ToolUIConfig(preset="custom", custom_html=big))))
    assert "UI_CUSTOM_HTML_TOO_LARGE" in codes


def test_undeclared_csp_origin_warns() -> None:
    html = '<html><script>fetch("https://api.external.example/data")</script></html>'
    codes = _codes(_connector(_tool(ToolUIConfig(preset="custom", custom_html=html))))
    assert "UI_CSP_UNDECLARED_DOMAIN" in codes


def test_declared_csp_origin_is_clean() -> None:
    html = '<html><script>fetch("https://api.external.example/data")</script></html>'
    ui = ToolUIConfig(
        preset="custom",
        custom_html=html,
        csp_connect_domains=["https://api.external.example"],
    )
    codes = _codes(_connector(_tool(ui)))
    assert "UI_CSP_UNDECLARED_DOMAIN" not in codes


def test_disabled_ui_is_not_linted() -> None:
    codes = _codes(_connector(_tool(ToolUIConfig(enabled=False, preset="chart"))))
    assert not {c for c in codes if c.startswith("UI_")}


def test_oversized_data_logo_warns() -> None:
    from elliot_core.types.connector import ConnectorBranding

    cfg = _connector(_tool(ToolUIConfig(preset="table", mapping={"columns": "id"})))
    cfg = cfg.model_copy(
        update={"branding": ConnectorBranding(logo="data:image/png;base64," + "A" * (70 * 1024))}
    )
    issues = lint_connector(cfg)
    match = [i for i in issues if i.code == "UI_BRANDING_LOGO_TOO_LARGE"]
    assert match and match[0].severity == "WARN" and match[0].tool_id is None


def test_small_data_logo_and_https_logo_are_clean() -> None:
    from elliot_core.types.connector import ConnectorBranding

    cfg = _connector(_tool(ToolUIConfig(preset="table", mapping={"columns": "id"})))
    small = cfg.model_copy(
        update={"branding": ConnectorBranding(logo="data:image/svg+xml;base64,PHN2Zz4=")}
    )
    assert "UI_BRANDING_LOGO_TOO_LARGE" not in {i.code for i in lint_connector(small)}
    # An https logo is a URL, never inlined — size rule does not apply.
    huge_url = cfg.model_copy(
        update={"branding": ConnectorBranding(logo="https://cdn.example/" + "a" * 100 + ".png")}
    )
    assert "UI_BRANDING_LOGO_TOO_LARGE" not in {i.code for i in lint_connector(huge_url)}
