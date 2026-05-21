"""Install / uninstall the Elliot trace hook into a coding agent's config.

``elliot trace install --harness <h>`` wires :mod:`elliot_core.trace.hook_adapter`
into the harness's own hook configuration so that, the next time the user runs
that agent locally, every tool call (plus the prompt and reasoning) is shipped
to the Agent Console. Each harness stores hooks differently:

* Claude Code — ``~/.claude/settings.json``        (JSON ``hooks`` block)
* Codex       — ``~/.codex/config.toml``           (``[[hooks.*]]`` tables)
* Cursor      — ``~/.cursor/hooks.json``           (JSON ``hooks`` block)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Substring that identifies an entry this installer wrote — used to keep
# install idempotent and to support a clean uninstall.
_MARKER = "elliot_core.trace.hook_adapter"
_CODEX_OPEN = "# >>> elliot trace hooks (elliot_core.trace.hook_adapter) >>>"
_CODEX_CLOSE = "# <<< elliot trace hooks <<<"

# Hook events captured per harness. PostToolUse / afterMCPExecution carry the
# tool call; the prompt and final-answer events round out the trace.
_CLAUDE_LIKE_EVENTS = ("PostToolUse", "UserPromptSubmit", "Stop")
_CURSOR_EVENTS = ("afterMCPExecution", "beforeSubmitPrompt")


def default_settings_path(harness: str) -> Path:
    """Return the canonical hook-config file for a harness."""
    home = Path.home()
    if harness == "claude-code":
        return home / ".claude" / "settings.json"
    if harness == "codex":
        return home / ".codex" / "config.toml"
    if harness == "cursor":
        return home / ".cursor" / "hooks.json"
    raise ValueError(f"unknown harness: {harness!r}")


def _hook_command(harness: str, event: str, python: str) -> str:
    return f"{python} -m elliot_core.trace.hook_adapter --harness {harness} --event {event}"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _install_claude_code(path: Path, python: str) -> None:
    data = _load_json(path)
    hooks = data.setdefault("hooks", {})
    for event in _CLAUDE_LIKE_EVENTS:
        entries = [e for e in hooks.get(event, []) if _MARKER not in json.dumps(e)]
        entry: dict[str, Any] = {
            "hooks": [
                {
                    "type": "command",
                    "command": _hook_command("claude-code", event, python),
                    "timeout": 5000,
                }
            ]
        }
        if event == "PostToolUse":
            entry["matcher"] = "mcp__.*"
        entries.append(entry)
        hooks[event] = entries
    _write_json(path, data)


def _install_cursor(path: Path, python: str) -> None:
    data = _load_json(path)
    data.setdefault("version", 1)
    hooks = data.setdefault("hooks", {})
    for event in _CURSOR_EVENTS:
        entries = [e for e in hooks.get(event, []) if _MARKER not in json.dumps(e)]
        entries.append({"command": _hook_command("cursor", event, python)})
        hooks[event] = entries
    _write_json(path, data)


def _codex_block(python: str) -> str:
    lines = [_CODEX_OPEN]
    for event in _CLAUDE_LIKE_EVENTS:
        lines.append(f"[[hooks.{event}]]")
        if event == "PostToolUse":
            lines.append('matcher = "mcp__.*"')
        lines.append(f'command = "{_hook_command("codex", event, python)}"')
        lines.append("")
    lines.append(_CODEX_CLOSE)
    return "\n".join(lines) + "\n"


def _strip_codex_block(text: str) -> str:
    if _CODEX_OPEN not in text or _CODEX_CLOSE not in text:
        return text
    before, _, rest = text.partition(_CODEX_OPEN)
    _, _, after = rest.partition(_CODEX_CLOSE)
    return (before.rstrip() + "\n" + after.lstrip()).strip() + "\n"


def _install_codex(path: Path, python: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    existing = _strip_codex_block(existing) if _MARKER in existing else existing
    block = _codex_block(python)
    body = f"{existing.rstrip()}\n\n{block}" if existing.strip() else block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def install(harness: str, *, settings_path: Path | None = None, python: str | None = None) -> Path:
    """Install the trace hook for ``harness``. Returns the config path written."""
    path = settings_path or default_settings_path(harness)
    runner = python or sys.executable
    if harness == "claude-code":
        _install_claude_code(path, runner)
    elif harness == "codex":
        _install_codex(path, runner)
    elif harness == "cursor":
        _install_cursor(path, runner)
    else:
        raise ValueError(f"unknown harness: {harness!r}")
    return path


def is_installed(harness: str, *, settings_path: Path | None = None) -> bool:
    """Whether the Elliot trace hook is present in ``harness``'s config.

    Every harness writes the same marker (the hook-adapter module path) into
    its command string, so a substring check works across the JSON (Claude
    Code / Cursor) and TOML (Codex) formats alike.
    """
    path = settings_path or default_settings_path(harness)
    if not path.exists():
        return False
    try:
        return _MARKER in path.read_text(encoding="utf-8")
    except OSError:
        return False


def uninstall(harness: str, *, settings_path: Path | None = None) -> Path:
    """Remove the trace hook for ``harness``. Returns the config path."""
    path = settings_path or default_settings_path(harness)
    if not path.exists():
        return path
    if harness == "codex":
        path.write_text(_strip_codex_block(path.read_text(encoding="utf-8")), encoding="utf-8")
        return path
    data = _load_json(path)
    hooks = data.get("hooks", {})
    for event, entries in list(hooks.items()):
        kept = [e for e in entries if _MARKER not in json.dumps(e)]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    _write_json(path, data)
    return path
