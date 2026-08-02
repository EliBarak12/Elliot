from __future__ import annotations

import re

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


class ConnectorBranding(BaseModel):
    """Brand identity applied to every MCP Apps view this connector serves.

    The views inherit the HOST's theme (background, text, fonts) so they stay
    legible inside Claude/ChatGPT in light and dark mode; branding layers the
    product's identity on top — the accent color drives highlights/focus/
    selection, and the logo renders in each view's header.
    """

    model_config = ConfigDict(extra="forbid")

    # Brand accent as a hex color (#rgb or #rrggbb). Used for highlights,
    # selection and focus states in the views — never for text/background,
    # which stay host-themed for legibility.
    accent: str | None = None
    # Optional accent override for dark host themes (brand colors often need
    # a lighter variant to read on dark backgrounds). Falls back to `accent`.
    accent_dark: str | None = None
    # Logo shown in each view's header. A `data:` URI (recommended — the host
    # CSP always allows data: images, so the view stays self-contained) or an
    # https URL, whose origin is auto-declared in the view's CSP resource
    # domains so hosts permit loading it.
    logo: str | None = None

    @field_validator("accent", "accent_dark")
    @classmethod
    def _validate_hex(cls, value: str | None) -> str | None:
        if value is not None and not _HEX_COLOR_RE.match(value):
            raise ValueError(f"must be a hex color like #c02434, got {value!r}")
        return value

    @field_validator("logo")
    @classmethod
    def _validate_logo(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not (value.startswith("data:image/") or value.startswith("https://")):
            raise ValueError("logo must be a data:image/... URI or an https:// URL")
        return value


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
