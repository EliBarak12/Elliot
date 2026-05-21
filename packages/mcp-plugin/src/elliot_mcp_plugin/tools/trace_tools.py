"""Trace-hook tools — let the user enable local agent-run capture.

MCP tool calls already reach the Agent Console on their own, but they don't
carry the user's prompt, the model's reasoning, or the final answer. The Elliot
trace hook fills that gap: once installed into a coding agent's config it ships
each local run to the connector runtime's ``/v1/trace/ingest`` so the full
context shows up in the console.

These tools wire that hook in from inside Elliot — the agent (or Studio, on the
user's behalf) can enable it without the user running the CLI by hand. They are
the programmatic counterpart to ``elliot trace install``.
"""

from __future__ import annotations

import os

import structlog
from mcp.server.fastmcp import FastMCP

from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.trace import SUPPORTED_HARNESSES
from elliot_core.trace.installer import (
    default_settings_path,
    install,
    is_installed,
    uninstall,
)
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)


def _runtime_url() -> str:
    return os.environ.get("ELLIOT_RUNTIME_URL", "http://localhost:3001").rstrip("/")


def _validate_harness(harness: str) -> None:
    if harness not in SUPPORTED_HARNESSES:
        raise ElliotError(
            "VALIDATION_UNKNOWN_HARNESS",
            f"harness must be one of {list(SUPPORTED_HARNESSES)}; got {harness!r}.",
            {"field": "harness", "allowed": list(SUPPORTED_HARNESSES)},
        )


def register_trace_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_trace_hook_status() -> dict:  # type: ignore[type-arg]
        """Report whether the Elliot trace hook is installed per agent harness.

        The hook is what streams the user's prompt, the model's reasoning, and
        the final answer into the Agent Console — MCP tool calls alone don't
        carry that context. Returns the runtime URL the hook posts to and, for
        each supported harness (claude-code, codex, cursor), whether it's
        installed and the config path it lives in.
        """
        return {
            "runtime_url": _runtime_url(),
            "harnesses": [
                {
                    "harness": h,
                    "installed": is_installed(h),
                    "config_path": str(default_settings_path(h)),
                }
                for h in SUPPORTED_HARNESSES
            ],
        }

    @mcp.tool()
    def elliot_install_trace_hook(harness: str = "claude-code") -> dict:  # type: ignore[type-arg]
        """Install the Elliot trace hook into a coding agent's config.

        After installing, the user restarts that agent; its prompts, reasoning,
        tool calls and final answers then appear live in the Agent Console.
        ``harness`` is one of: claude-code, codex, cursor.
        """
        try:
            _validate_harness(harness)
            path = install(harness)
            log.info("trace_hook.installed", harness=harness, path=str(path))
            return {
                "status": "installed",
                "harness": harness,
                "config_path": str(path),
                "runtime_url": _runtime_url(),
                "next": (
                    f"Restart {harness}. Its prompts, reasoning, tool calls and "
                    "final answers will now stream into the Agent Console."
                ),
            }
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("trace_hook.install_failed", harness=harness, error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("TRACE_HOOK_INSTALL_FAILED", str(exc)))

    @mcp.tool()
    def elliot_uninstall_trace_hook(harness: str = "claude-code") -> dict:  # type: ignore[type-arg]
        """Remove the Elliot trace hook from a coding agent's config.

        ``harness`` is one of: claude-code, codex, cursor.
        """
        try:
            _validate_harness(harness)
            path = uninstall(harness)
            log.info("trace_hook.uninstalled", harness=harness, path=str(path))
            return {"status": "removed", "harness": harness, "config_path": str(path)}
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("trace_hook.uninstall_failed", harness=harness, error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("TRACE_HOOK_UNINSTALL_FAILED", str(exc)))
