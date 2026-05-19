"""Elliot MCP plugin — FastAPI HTTP server exposing the MCP toolset."""

__version__ = "0.1.0"

from .connector_loader import load_connector, load_secrets
from .server import build_tool_list, create_elliot_server, create_server, run_stdio

__all__ = [
    "__version__",
    "build_tool_list",
    "create_elliot_server",
    "create_server",
    "run_stdio",
    "load_connector",
    "load_secrets",
]
