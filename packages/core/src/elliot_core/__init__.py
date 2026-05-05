"""Elliot Core — AI AX data connector library."""

__version__ = "0.1.0"

from elliot_core.connector.builder import ConnectorBuilder
from elliot_core.connector.schema_gen import to_mcp_tool_schema
from elliot_core.connector.serializer import deserialize_connector, serialize_connector
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
from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.sqlite.flattener import flatten
from elliot_core.tools.executor import ToolExecutor
from elliot_core.tools.registry import ToolRegistry
from elliot_core.tools.skill_runner import execute_skill
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
from elliot_core.types.connector import ProductContext
from elliot_core.types.sqlite import FlattenedTable, FlattenResult
from elliot_core.workspace.store import WorkspaceStore

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
    "ProductContext",
    "FetchResult",
    "FilterCondition",
    "FilterGroup",
    "FlattenResult",
    "FlattenedTable",
    "PaginationConfig",
    "ParameterDefinition",
    "ResponseShape",
    "ReturnField",
    "SkillDefinition",
    "SkillStep",
    "SourceConfig",
    "ToolDefinition",
    "ToolResult",
    # sqlite
    "SQLiteEngine",
    "flatten",
    # tools
    "ToolExecutor",
    "ToolRegistry",
    "execute_skill",
    # connector
    "ConnectorBuilder",
    "deserialize_connector",
    "serialize_connector",
    "to_mcp_tool_schema",
    # workspace
    "WorkspaceStore",
]
