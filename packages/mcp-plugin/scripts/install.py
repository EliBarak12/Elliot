#!/usr/bin/env python3
"""
Registers Elliot with Claude Code, Codex, and OpenClaw automatically.
1. Writes .mcp.json at project root       -> Claude Code project-level auto-discovery
2. Runs `claude mcp add-json`             -> Claude Code user-level registration
3. Writes .codex/config.toml             -> Codex project-level auto-discovery
4. Writes ~/.codex/config.toml           -> Codex user-level registration
5. Writes ~/.openclaw/openclaw.json      -> OpenClaw user-level registration
"""

import json
import subprocess
from pathlib import Path

PLUGIN_URL = "http://localhost:3000/mcp/"
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# 1. Claude Code — project .mcp.json
mcp_json = PROJECT_ROOT / ".mcp.json"
config = json.loads(mcp_json.read_text()) if mcp_json.exists() else {"mcpServers": {}}
config.setdefault("mcpServers", {})["elliot"] = {"type": "http", "url": PLUGIN_URL}
mcp_json.write_text(json.dumps(config, indent=2))
print("✓ .mcp.json written — Claude Code auto-loads on folder open")

# 2. Claude Code — user scope via CLI
try:
    subprocess.run(
        [
            "claude",
            "mcp",
            "add-json",
            "elliot",
            json.dumps({"type": "http", "url": PLUGIN_URL}),
            "--scope",
            "user",
        ],
        check=True,
        capture_output=True,
    )
    print("✓ Claude Code: registered at user scope")
except (subprocess.CalledProcessError, FileNotFoundError):
    print("  claude CLI not found — project .mcp.json is sufficient")

# 3. Codex — project .codex/config.toml
codex_dir = PROJECT_ROOT / ".codex"
codex_dir.mkdir(exist_ok=True)
toml_entry = f'\n[mcp_servers.elliot]\nurl = "{PLUGIN_URL}"\n'
codex_project = codex_dir / "config.toml"
existing = codex_project.read_text() if codex_project.exists() else ""
if "[mcp_servers.elliot]" not in existing:
    codex_project.write_text(existing + toml_entry)
print("✓ .codex/config.toml written — Codex auto-loads on folder open")

# 4. Codex — user ~/.codex/config.toml
try:
    user_codex = Path.home() / ".codex" / "config.toml"
    user_codex.parent.mkdir(exist_ok=True)
    existing_user = user_codex.read_text() if user_codex.exists() else ""
    if "[mcp_servers.elliot]" not in existing_user:
        user_codex.write_text(existing_user + toml_entry)
        print("✓ Codex: registered at user scope")
except Exception:
    print("  Could not write ~/.codex/config.toml — project-level is sufficient")

# 5. OpenClaw — user ~/.openclaw/openclaw.json
# OpenClaw nests servers two levels deep (mcp.servers.<name>) and expects a
# `transport` field; remote HTTP servers use the "streamable-http" spelling.
try:
    openclaw_config = Path.home() / ".openclaw" / "openclaw.json"
    openclaw_config.parent.mkdir(parents=True, exist_ok=True)
    oc_data = json.loads(openclaw_config.read_text()) if openclaw_config.exists() else {}
    oc_servers = oc_data.setdefault("mcp", {}).setdefault("servers", {})
    oc_servers["elliot"] = {"transport": "streamable-http", "url": PLUGIN_URL}
    openclaw_config.write_text(json.dumps(oc_data, indent=2))
    print("✓ OpenClaw: registered at ~/.openclaw/openclaw.json")
except Exception:
    print("  Could not write ~/.openclaw/openclaw.json — skipping OpenClaw")

print("\nDone! Now run: make dev")
