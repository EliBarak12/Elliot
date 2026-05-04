"""Elliot Core — AI AX data connector library."""

__version__ = "0.1.0"

from elliot_core.errors import (
    AuthError,
    ElliotError,
    NotFoundError,
    RateLimitError,
    SourceFetchError,
    ValidationError,
    is_elliot_error,
    to_mcp_error_content,
)
from elliot_core.types import (
    ApiRequestMapping,
    AuthConfig,
    ConnectorConfig,
    FetchResult,
    FilterCondition,
    FilterGroup,
    PaginationConfig,
    ParameterDefinition,
    ResponseShape,
    ReturnField,
    SkillDefinition,
    SkillStep,
    SourceConfig,
    ToolDefinition,
    ToolResult,
)

__all__ = [
    "__version__",
    # errors
    "AuthError",
    "ElliotError",
    "NotFoundError",
    "RateLimitError",
    "SourceFetchError",
    "ValidationError",
    "is_elliot_error",
    "to_mcp_error_content",
    # types
    "ApiRequestMapping",
    "AuthConfig",
    "ConnectorConfig",
    "FetchResult",
    "FilterCondition",
    "FilterGroup",
    "PaginationConfig",
    "ParameterDefinition",
    "ResponseShape",
    "ReturnField",
    "SkillDefinition",
    "SkillStep",
    "SourceConfig",
    "ToolDefinition",
    "ToolResult",
]
