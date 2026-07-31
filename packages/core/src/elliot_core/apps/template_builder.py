"""Build the ui:// HTML documents served for tools with a UI config."""

from __future__ import annotations

import json
import re
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any

import structlog
from mcp.server.apps import Apps, ResourceCsp

from elliot_core.types.connector import ConnectorBranding, ConnectorConfig
from elliot_core.types.tool import ToolDefinition, ToolUIConfig

log = structlog.get_logger(__name__)

# Hard cap for a custom template, enforced at lint time and re-checked here
# defensively: views are inlined documents a host downloads per render/cache.
MAX_CUSTOM_HTML_BYTES = 256 * 1024

_CONFIG_SCRIPT_RE = re.compile(
    r'(<script type="application/json" id="elliot-ui-config">).*?(</script>)',
    re.DOTALL,
)

_DEFAULT_VISIBILITY = ["model", "app"]


def ui_resource_uri(connector_slug: str | None, tool_id: str) -> str:
    """The ui:// URI a tool's view is served at."""
    return f"ui://{connector_slug or 'connector'}/{tool_id}"


def _load_preset_shell() -> str:
    """The committed single-file bundle built by packages/ui-kit."""
    asset = importlib_resources.files("elliot_core") / "apps" / "assets" / "elliot-app.html"
    return asset.read_text(encoding="utf-8")


def _inject_config(html: str, config: dict[str, Any]) -> str:
    """Replace the #elliot-ui-config placeholder with this tool's config.

    ``</`` is escaped so a value can never close the script tag early.
    """
    payload = json.dumps(config, ensure_ascii=False).replace("</", "<\\/")
    replaced, count = _CONFIG_SCRIPT_RE.subn(rf"\g<1>{payload}\g<2>", html, count=1)
    if count == 0:
        log.warning("apps.template.no_config_slot")
        return html
    return replaced


def _resolve_custom_html(ui: ToolUIConfig, connector_dir: Path | None) -> str | None:
    """The author's own template: inline HTML (post-export) or a file path
    relative to the connector directory. Returns None when unusable — the
    caller falls back to the preset shell so a bad custom template degrades
    to a working view rather than a broken tool."""
    raw = ui.custom_html
    if not raw:
        return None
    if raw.lstrip().startswith("<"):
        html = raw
    else:
        if connector_dir is None:
            log.warning("apps.custom_html.no_connector_dir", path=raw)
            return None
        candidate = (connector_dir / raw).resolve()
        try:
            candidate.relative_to(connector_dir.resolve())
        except ValueError:
            log.warning("apps.custom_html.outside_connector_dir", path=raw)
            return None
        try:
            html = candidate.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("apps.custom_html.unreadable", path=raw, error=str(exc))
            return None
    if len(html.encode("utf-8")) > MAX_CUSTOM_HTML_BYTES:
        log.warning("apps.custom_html.too_large", tool_bytes=len(html))
        return None
    return html


def build_tool_app_html(
    tool: ToolDefinition,
    ui: ToolUIConfig,
    *,
    connector_slug: str | None = None,
    connector_dir: Path | None = None,
    branding: ConnectorBranding | None = None,
) -> str:
    """The HTML document served at this tool's ui:// URI."""
    if ui.preset == "custom":
        custom = _resolve_custom_html(ui, connector_dir)
        if custom is not None:
            return custom
        # Degrade to the preset shell (auto) rather than serving nothing.
    config: dict[str, Any] = {
        "tool_id": tool.id,
        "title": ui.title or tool.name,
        "preset": ui.preset if ui.preset != "custom" else "auto",
        "mapping": ui.mapping,
        "category": tool.category,
    }
    if branding is not None and (branding.accent or branding.logo):
        config["branding"] = {
            "accent": branding.accent,
            "accent_dark": branding.accent_dark,
            "logo": branding.logo,
        }
    _ = connector_slug  # part of the stable signature; the config is per-tool
    return _inject_config(_load_preset_shell(), config)


def tool_ui_meta(ui: ToolUIConfig, resource_uri: str) -> dict[str, Any]:
    """The ``_meta`` dict stamped on a UI-enabled tool's listing entry."""
    entry: dict[str, Any] = {"resourceUri": resource_uri}
    if list(ui.visibility) != _DEFAULT_VISIBILITY:
        entry["visibility"] = list(ui.visibility)
    return {"ui": entry}


def inline_custom_html(cfg: ConnectorConfig, base_dir: Path) -> ConnectorConfig:
    """Return a copy of ``cfg`` with each tool's ``custom_html`` *path*
    replaced by the file's contents, so an exported/published spec is
    self-contained (Elliot Cloud stores only the spec JSON — a path into the
    author's local checkout would dangle). Values that are already inline
    HTML, unset, or unreadable pass through unchanged; lint catches the
    unreadable case as UI_CUSTOM_HTML_MISSING before export gates on it."""
    changed = False
    tools = []
    for tool in cfg.tools:
        ui = tool.ui
        if ui is not None and ui.custom_html and not ui.custom_html.lstrip().startswith("<"):
            html = _resolve_custom_html(ui, base_dir)
            if html is not None:
                tools.append(
                    tool.model_copy(update={"ui": ui.model_copy(update={"custom_html": html})})
                )
                changed = True
                continue
        tools.append(tool)
    if not changed:
        return cfg
    log.info("apps.custom_html.inlined", connector=cfg.slug)
    return cfg.model_copy(update={"tools": tools})


def build_apps_extension(cfg: ConnectorConfig, *, connector_dir: Path | None = None) -> Apps | None:
    """Assemble the MCP Apps extension for a connector, or ``None`` when no
    enabled tool declares a UI.

    Must be called BEFORE constructing the server — the SDK consumes
    extensions at ``MCPServer.__init__`` and they cannot be added later.
    """
    apps = Apps()
    count = 0
    for tool in cfg.tools:
        if not getattr(tool, "enabled", True):
            continue
        ui = tool.ui
        if ui is None or not ui.enabled:
            continue
        uri = ui_resource_uri(cfg.slug, tool.id)
        html = build_tool_app_html(
            tool,
            ui,
            connector_slug=cfg.slug,
            connector_dir=connector_dir,
            branding=cfg.branding,
        )
        # An https logo needs its origin declared for the host CSP's img-src;
        # data: URIs are always allowed and need nothing.
        resource_domains: list[str] = []
        logo = cfg.branding.logo if cfg.branding else None
        if logo and logo.startswith("https://"):
            resource_domains.append("https://" + logo.removeprefix("https://").split("/", 1)[0])
        apps.add_html_resource(
            uri,
            html,
            name=f"{tool.id}_view",
            title=ui.title or tool.name,
            description=f"Interactive view for the {tool.id} tool.",
            csp=(
                ResourceCsp(
                    connect_domains=list(ui.csp_connect_domains) or None,
                    resource_domains=resource_domains or None,
                )
                if ui.csp_connect_domains or resource_domains
                else None
            ),
            prefers_border=ui.prefer_border,
        )
        count += 1
    if count == 0:
        return None
    log.info("apps.extension.built", views=count, connector=cfg.slug)
    return apps
