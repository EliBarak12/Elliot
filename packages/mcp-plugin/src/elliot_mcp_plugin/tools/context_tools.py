"""Context tools — set and inspect the product context for the session."""

from __future__ import annotations

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
        clear: bool = False,
    ) -> dict:  # type: ignore[type-arg]
        """Set connector-level branding for MCP Apps views: accent color and logo.

        The accent (hex, e.g. ``#c02434``) drives highlights/selection/focus in
        every tool view; ``accent_dark`` optionally overrides it on dark host
        themes. ``logo`` is a ``data:image/...`` URI (recommended) or an
        ``https://`` URL shown in each view's header. Text and background
        always follow the host theme, so views stay legible in any client.

        Fields you pass are merged over the current branding; pass
        ``clear=True`` to reset everything first (``clear=True`` alone removes
        branding entirely). Branding is applied on the next
        ``elliot_build_connector`` and immediately in ``elliot_preview_tool_ui``.
        """
        try:
            base = {} if clear or session.branding is None else session.branding.model_dump()
            for key, value in (("accent", accent), ("accent_dark", accent_dark), ("logo", logo)):
                if value is not None:
                    base[key] = value
            branding = ConnectorBranding.model_validate(base) if any(base.values()) else None
            session.branding = branding
            session.save()
            log.info(
                "branding.set",
                has_accent=bool(branding and branding.accent),
                has_logo=bool(branding and branding.logo),
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
        """Return the connector-level branding (accent colors + logo) for this session."""
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
