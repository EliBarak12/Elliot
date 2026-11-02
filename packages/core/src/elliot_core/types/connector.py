from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import SkillDefinition, ToolDefinition


class ProductContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    base_url: str = ""
    version: str = ""


_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


_FONT_FAMILY_RE = re.compile(r"^[A-Za-z0-9 _\-]{1,60}$")


class ConnectorBranding(BaseModel):
    """The connector's design system: one brand, applied to every MCP Apps view.

    Set once (``elliot_set_branding``, the dashboard's Branding card, or the
    cloud's "import from your website") and every tool's view — tables,
    cards, detail, metrics, charts — renders in the product's identity, so
    the whole app inside Claude or ChatGPT reads as one branded surface
    rather than a set of generic widgets.

    Every token is optional and layered over the host theme:

    * Identity — ``name`` and ``logo`` in each view's header.
    * Color — ``accent`` (buttons, selection, focus, highlights) with an
      optional ``accent_dark`` for dark host themes and ``accent_foreground``
      for text on the accent (derived for contrast when omitted). Surfaces
      (``background``/``foreground`` and their ``_dark`` pair) stay
      host-themed unless set, which keeps views legible in any client.
    * Type — ``font_family``, optionally loaded from ``font_url`` (an https
      stylesheet such as a Google Fonts ``css2`` link; its origin is declared
      in each view's CSP automatically).
    * Shape and rhythm — ``radius`` and ``density``.
    """

    model_config = ConfigDict(extra="forbid")

    # Brand name shown beside the logo in each view's header.
    name: str | None = None
    # Brand accent as a hex color (#rgb or #rrggbb).
    accent: str | None = None
    # Optional accent override for dark host themes (brand colors often need
    # a lighter variant to read on dark backgrounds). Falls back to `accent`.
    accent_dark: str | None = None
    # Text/icon color on the accent (buttons, selected chips). Derived from
    # the accent's luminance when omitted.
    accent_foreground: str | None = None
    # Brand surfaces. Unset → the host's own background/text (recommended).
    background: str | None = None
    foreground: str | None = None
    background_dark: str | None = None
    foreground_dark: str | None = None
    # CSS font family name, e.g. "Inter" or "IBM Plex Sans". Falls back to
    # the host's font, then the system UI font.
    font_family: str | None = None
    # https stylesheet that loads `font_family` (e.g. a Google Fonts css2 URL).
    font_url: str | None = None
    # Corner rounding across cards, inputs, chips and buttons.
    radius: Literal["none", "sm", "md", "lg", "xl"] | None = None
    # Spacing and type scale: compact fits more rows, spacious reads calmer.
    density: Literal["compact", "comfortable", "spacious"] | None = None
    # Logo shown in each view's header. A `data:` URI (recommended — the host
    # CSP always allows data: images, so the view stays self-contained) or an
    # https URL, whose origin is auto-declared in the view's CSP resource
    # domains so hosts permit loading it.
    logo: str | None = None

    @field_validator(
        "accent",
        "accent_dark",
        "accent_foreground",
        "background",
        "foreground",
        "background_dark",
        "foreground_dark",
    )
    @classmethod
    def _validate_hex(cls, value: str | None) -> str | None:
        if value is not None and not _HEX_COLOR_RE.match(value):
            raise ValueError(f"must be a hex color like #c02434, got {value!r}")
        return value

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            return None
        if len(value) > 60:
            raise ValueError("name must be at most 60 characters")
        return value

    @field_validator("font_family")
    @classmethod
    def _validate_font_family(cls, value: str | None) -> str | None:
        # Interpolated into CSS: letters, digits, spaces, '-' and '_' only, so
        # a value can never close the declaration and inject rules.
        if value is not None and not _FONT_FAMILY_RE.match(value):
            raise ValueError(
                "font_family must be a single family name (letters, digits, spaces, '-', '_')"
            )
        return value

    @field_validator("font_url")
    @classmethod
    def _validate_font_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("https://"):
            raise ValueError("font_url must be an https:// stylesheet URL")
        return value

    @field_validator("logo")
    @classmethod
    def _validate_logo(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not (value.startswith("data:image/") or value.startswith("https://")):
            raise ValueError("logo must be a data:image/... URI or an https:// URL")
        return value

    def is_empty(self) -> bool:
        """True when no token is set — equivalent to having no branding."""
        return not any(v is not None for v in self.model_dump().values())


class ConnectorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    slug: str
    version: str
    description: str = ""
    instructions: str = ""
    sources: list[SourceConfig] = []
    tools: list[ToolDefinition] = []
    skills: list[SkillDefinition] = []
    # Brand identity for the connector's MCP Apps views (None → Elliot's
    # neutral defaults; text/background always follow the host theme).
    branding: ConnectorBranding | None = None

    @model_validator(mode="after")
    def _validate_source_refs(self) -> ConnectorConfig:
        source_ids = {s.id for s in self.sources}
        for tool in self.tools:
            for sid in tool.source_ids:
                if sid not in source_ids:
                    raise ValueError(
                        f"Tool '{tool.id}' references unknown source '{sid}'. "
                        f"Available: {sorted(source_ids)}"
                    )
            if tool.category == "READ" and not tool.source_ids and not tool.sql:
                raise ValueError(
                    f"READ tool '{tool.id}' must declare at least one source_id or sql"
                )
        return self
