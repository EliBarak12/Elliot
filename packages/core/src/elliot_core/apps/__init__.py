"""MCP Apps support: serve per-tool UI templates at ui:// URIs.

Implements the ext-apps spec (2026-01-26, extension id
``io.modelcontextprotocol/ui``) for Elliot connectors: a tool with a
``ToolUIConfig`` gets a single-file HTML view — the shadcn-styled preset
bundle built by packages/ui-kit and committed under ``apps/assets/``, or the
author's own HTML — served as a ``ui://<slug>/<tool_id>`` resource with
``text/html;profile=mcp-app``, and its listing stamped with
``_meta.ui.resourceUri`` so hosts (Claude, ChatGPT, Cursor, Studio's
preview) render it in a sandboxed iframe.
"""

from elliot_core.apps.template_builder import (
    build_apps_extension,
    build_tool_app_html,
    tool_ui_meta,
    ui_resource_uri,
)

__all__ = [
    "build_apps_extension",
    "build_tool_app_html",
    "tool_ui_meta",
    "ui_resource_uri",
]
