"""Context tools — set and inspect the product context for the session."""

from __future__ import annotations

from typing import Literal

import structlog

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.mcp_compat import FastMCP
from elliot_core.types.connector import ConnectorBranding, ProductContext
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)


def register_context_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_set_context(
        name: str,
        description: str = "",
        base_url: str = "",
        version: str = "",
    ) -> dict:  # type: ignore[type-arg]
        """Set the product context (name, description, base URL) for the current session."""
        try:
            session.product_context = ProductContext(
                name=name, description=description, base_url=base_url, version=version
            )
            session.save()
            return {"status": "ok", "context": session.product_context.model_dump()}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("context.set.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_get_context() -> dict:  # type: ignore[type-arg]
        """Return the current product context for this session."""
        try:
            if not session.product_context:
                return {"context": None}
            return {"context": session.product_context.model_dump()}
        except Exception as exc:
            log.error("context.get.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_set_branding(
        accent: str | None = None,
        accent_dark: str | None = None,
        logo: str | None = None,
        name: str | None = None,
        accent_foreground: str | None = None,
        background: str | None = None,
        foreground: str | None = None,
        background_dark: str | None = None,
        foreground_dark: str | None = None,
        font_family: str | None = None,
        font_url: str | None = None,
        radius: Literal["none", "sm", "md", "lg", "xl"] | None = None,
        density: Literal["compact", "comfortable", "spacious"] | None = None,
        clear: bool = False,
    ) -> dict:  # type: ignore[type-arg]
        """Set the connector's design system — one brand for every tool view.

        One call brands the whole app as hosts like Claude render it: every
        tool's MCP Apps view (table, cards, detail, metrics, chart) picks up
        the same identity.

        Identity: ``name`` and ``logo`` (a ``data:image/...`` URI, recommended,
        or an ``https://`` URL) in each view's header. Color: ``accent`` (hex,
        e.g. ``#c02434``) for buttons, selection and highlights, optional
        ``accent_dark`` for dark host themes and ``accent_foreground`` for text
        on the accent (derived when omitted). Surfaces follow the host theme
        unless ``background``/``foreground`` (and ``_dark``) are set. Type:
        ``font_family`` (e.g. ``Inter``), loaded from ``font_url`` (an https
        stylesheet such as a Google Fonts css2 link) when it is not a system
        font. Shape and rhythm: ``radius`` (none|sm|md|lg|xl) and ``density``
        (compact|comfortable|spacious).

        Fields you pass are merged over the current branding; pass
        ``clear=True`` to reset everything first (``clear=True`` alone removes
        branding entirely). Branding is applied on the next
        ``elliot_build_connector`` and immediately in ``elliot_preview_tool_ui``.
        """
        try:
            base = {} if clear or session.branding is None else session.branding.model_dump()
            updates = {
                "accent": accent,
                "accent_dark": accent_dark,
                "logo": logo,
                "name": name,
                "accent_foreground": accent_foreground,
                "background": background,
                "foreground": foreground,
                "background_dark": background_dark,
                "foreground_dark": foreground_dark,
                "font_family": font_family,
                "font_url": font_url,
                "radius": radius,
                "density": density,
            }
            for key, value in updates.items():
                if value is not None:
                    base[key] = value
            candidate = ConnectorBranding.model_validate(base)
            branding = None if candidate.is_empty() else candidate
            session.branding = branding
            session.save()
            log.info(
                "branding.set",
                has_accent=bool(branding and branding.accent),
                has_logo=bool(branding and branding.logo),
                tokens=sorted(
                    k for k, v in (branding.model_dump() if branding else {}).items() if v
                ),
                cleared=branding is None,
            )
            return {
                "status": "ok",
                "branding": branding.model_dump() if branding else None,
            }
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("branding.set.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("VALIDATION_ERROR", str(exc)))

    @mcp.tool()
    def elliot_get_branding() -> dict:  # type: ignore[type-arg]
        """Return the connector's design system (brand tokens) for this session."""
        try:
            session.refresh_from_disk()
            return {"branding": session.branding.model_dump() if session.branding else None}
        except Exception as exc:
            log.error("branding.get.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_get_session_state() -> dict:  # type: ignore[type-arg]
        """Return a summary of the current session: sources, tools, skills, connector status."""
        try:
            # The Studio polls this every few seconds to drive the live
            # activity toasts and the Header counts; pick up anything the
            # agent has written since our last check (including from a
            # separate plugin process sharing the same workspace).
            session.refresh_from_disk()
            return {
                "source_count": len(session.sources),
                "tool_count": len(session.registry.get_all()),
                "skill_count": len(session.registry.get_all_skills()),
                "product_context": (
                    session.product_context.model_dump() if session.product_context else None
                ),
                "runtime_running": (
                    session.runtime_process is not None and session.runtime_process.poll() is None
                ),
                "connector_built": session.connector is not None,
            }
        except Exception as exc:
            log.error("session.state.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))
