"""Elliot CLI — lint, eval, init, status, and connect subcommands."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elliot_core.types import ConnectorConfig

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_TEMPLATE_DESCRIPTIONS = {
    "rest-api-key": "REST API with API key header auth",
    "postgres-readonly": "PostgreSQL read-only connector",
    "paginated-rest": "REST API with cursor/offset pagination",
    "openapi-petstore": "Full Petstore example (docs/tutorials)",
}


def _load_connector(path: str | Path) -> ConnectorConfig:  # noqa: F821
    from elliot_core.connector.serializer import deserialize_connector

    p = Path(path)
    if not p.exists():
        print(f"Error: connector file not found: {p}", file=sys.stderr)
        sys.exit(1)
    return deserialize_connector(p.read_text(encoding="utf-8"))


def _cmd_lint(args: argparse.Namespace) -> None:
    from elliot_core.linter import lint_connector

    config = _load_connector(args.path)
    issues = lint_connector(config)

    errors = [i for i in issues if i.severity == "ERROR"]
    warns = [i for i in issues if i.severity == "WARN"]
    infos = [i for i in issues if i.severity == "INFO"]

    for issue in issues:
        icon = {"ERROR": "X", "WARN": "!", "INFO": "i"}[issue.severity]
        tool = f"[{issue.tool_id}]" if issue.tool_id else "[connector]"
        print(f"[{icon}] {issue.severity:<5} {tool:<20} {issue.code}")
        print(f"      {issue.message}")
        print(f"      Fix: {issue.suggestion}\n")

    total = len(issues)
    print(f"{total} issue(s): {len(errors)} errors, {len(warns)} warnings, {len(infos)} info")
    sys.exit(1 if errors else 0)


def _cmd_scan(args: argparse.Namespace) -> None:
    """Aggregate lint + quality analysis into a single agent-readiness report."""
    from elliot_core.eval.quality import analyze_connector_quality
    from elliot_core.linter import lint_connector

    config = _load_connector(args.path)
    issues = lint_connector(config)
    quality = analyze_connector_quality(config)

    errors = [i for i in issues if i.severity == "ERROR"]
    warns = [i for i in issues if i.severity == "WARN"]
    infos = [i for i in issues if i.severity == "INFO"]

    print(f"\nElliot Scan — {config.name} ({len(config.tools)} tools)")
    print("─" * 60)
    print(f"Quality score: {quality.overall_score}/100")
    print()

    for issue in issues:
        icon = {"ERROR": "X", "WARN": "!", "INFO": "i"}[issue.severity]
        tool = f"[{issue.tool_id}]" if issue.tool_id else "[connector]"
        print(f"[{icon}] {issue.severity:<5} {tool:<22} {issue.code}")
        print(f"      {issue.message}")
        print(f"      Fix: {issue.suggestion}\n")

    print(
        f"{len(issues)} lint issue(s): {len(errors)} errors, "
        f"{len(warns)} warnings, {len(infos)} info"
    )
    print(
        "Next: build the connector, then run a Petri-style audit "
        "(prompt `audit_connector`) to exercise the tools with sub-agents."
    )
    sys.exit(1 if errors else 0)


def _cmd_eval(args: argparse.Namespace) -> None:
    import asyncio

    from elliot_core.eval_types import load_eval_suite

    suite = load_eval_suite(args.path)

    connector_path = args.connector or (
        Path(args.path).parent / f"{suite.connector}.connector.json"
    )
    config = _load_connector(connector_path)

    from elliot_core.eval_runner import EvalRunner

    runner = EvalRunner(config)
    results = asyncio.run(runner.run_suite(suite))

    passed = sum(1 for r in results if r.passed)
    for r in results:
        icon = "OK" if r.passed else "FAIL"
        token_warn = " [large]" if r.token_estimate > 500 else ""
        print(
            f"[{icon}]  {r.case_id:<35} {r.result_rows} rows  "
            f"{r.token_estimate} tokens  {r.duration_ms}ms{token_warn}"
        )
        for fail in r.failures:
            print(f"       - {fail}")

    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)


def _cmd_init(args: argparse.Namespace) -> None:
    if args.list:
        print("Available templates:")
        for name, desc in _TEMPLATE_DESCRIPTIONS.items():
            print(f"  {name:<25} {desc}")
        return

    # Accept both `elliot init NAME [OUT]` (positional) and the legacy
    # `elliot init --template NAME [OUT]`. When the flag is used, the first
    # positional ("template") actually carries the output filename.
    template_opt = getattr(args, "template_opt", None)
    if template_opt:
        template = template_opt
        output = args.output or args.template
    else:
        template = args.template
        output = args.output

    if not template:
        print("Error: provide a TEMPLATE name (see: elliot init --list)", file=sys.stderr)
        sys.exit(1)

    src = _TEMPLATES_DIR / f"{template}.connector.json"
    if not src.exists():
        print(f"Error: unknown template '{template}'. Run: elliot init --list", file=sys.stderr)
        sys.exit(1)

    dest = Path(output or f"{template}.connector.json")
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Created {dest}")
    print(f"Next: elliot lint {dest}")


def _cmd_export_plugin(args: argparse.Namespace) -> None:
    """Scaffold an installable Codex + Claude Code plugin from a connector."""
    from elliot_core.errors import ElliotError
    from elliot_core.plugin_export import export_plugin

    src = Path(args.path)
    if not src.exists():
        print(f"Error: connector file not found: {src}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out) if args.out else Path(f"{src.stem.split('.')[0]}-plugin")
    if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
        print(
            f"Error: {out_dir} already exists and is not empty. Pass --force to overwrite.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        written = export_plugin(src, out_dir)
    except (FileNotFoundError, ElliotError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\nExported plugin to {out_dir}/")
    for path in written:
        print(f"  + {path.relative_to(out_dir)}")
    print("\n  Install in Claude Code:")
    print(f"    /plugin marketplace add {out_dir.resolve()}")
    print("\n  Install in Codex:")
    print(f"    codex plugin marketplace add {out_dir.resolve()}")
    print(f"\n  See {out_dir}/README.md for prerequisites and secrets.\n")


def _cmd_status(args: argparse.Namespace) -> None:
    import httpx

    plugin_url = os.environ.get("ELLIOT_PLUGIN_URL", "http://localhost:3000")
    runtime_url = os.environ.get("ELLIOT_RUNTIME_URL", "http://localhost:3001")
    studio_url = os.environ.get("ELLIOT_STUDIO_URL", "http://localhost:5173")
    db_url = os.environ.get("ELLIOT_DB_URL", "sqlite:///.elliot/observations.db")

    results: list[tuple[str, str, bool, str]] = []

    for name, url, detail_path in [
        ("plugin", plugin_url, "/health"),
        ("runtime", runtime_url, "/health"),
        ("studio", studio_url, None),
    ]:
        try:
            path = detail_path or "/"
            r = httpx.get(f"{url}{path}", timeout=3)
            detail = ""
            if r.status_code == 200 and detail_path:
                data = r.json()
                if name == "runtime":
                    connector = data.get("connector", "")
                    detail = f"  connector: {connector}" if connector else ""
            results.append((name, url, True, detail))
        except Exception:
            results.append((name, url, False, ""))

    try:
        from elliot_connector_runtime.observation_store import ObservationStore

        store = ObservationStore(db_url)
        count = len(store.recent_tool_calls(10000))
        results.append(("database", db_url, True, f"  {count} tool calls"))
    except Exception:
        results.append(("database", db_url, False, ""))

    # The runtime is connector-bound and started on demand by
    # elliot_start_runtime — it is expected to be down until a connector is
    # deployed, so it never counts toward the failure exit code.
    _optional = {"runtime"}

    print("\nElliot Services")
    print("─" * 56)
    all_ok = True
    for name, url, ok, detail in results:
        icon = "✓" if ok else "✗"
        if ok:
            state = "running"
        elif name in _optional:
            state = "not running (starts on demand when you deploy a connector)"
        else:
            state = "not reachable"
        print(f"  {name:<10} {url:<35} {icon} {state}{detail}")
        if not ok and name not in _optional:
            all_ok = False

    print()
    if all_ok:
        print("  All required services healthy.")
    else:
        failed = sum(1 for n, _, ok, _ in results if not ok and n not in _optional)
        print(f"  {failed} service(s) not reachable. Is honcho running? Try: make dev")
        sys.exit(1)


def _write_json_merge(
    path: Path, key: str, entry_key: str, entry_value: object, dry_run: bool = False
) -> bool:
    """Merge {key: {entry_key: entry_value}} into a JSON file. Returns True if changed.

    When ``dry_run`` is set, nothing is written — the return value still
    reflects whether a write *would* have changed the file.
    """
    data: dict[str, dict[str, object]] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except json.JSONDecodeError:
            pass
    servers = data.setdefault(key, {})
    if servers.get(entry_key) == entry_value:
        return False
    servers[entry_key] = entry_value
    if dry_run:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _write_openclaw_json(path: Path, section: str, mcp_url: str, dry_run: bool = False) -> bool:
    """Merge an Elliot MCP server into an OpenClaw ``openclaw.json``.

    OpenClaw nests servers two levels deep — ``mcp.servers.<name>`` — and
    expects a ``transport`` field; remote HTTP servers use the canonical
    ``"streamable-http"`` spelling. Returns True if the file changed. When
    ``dry_run`` is set, nothing is written.
    """
    entry: dict[str, str] = {"transport": "streamable-http", "url": mcp_url}
    data: dict[str, object] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except json.JSONDecodeError:
            pass
    mcp_block = data.setdefault("mcp", {})
    if not isinstance(mcp_block, dict):
        mcp_block = {}
        data["mcp"] = mcp_block
    servers = mcp_block.setdefault("servers", {})
    if not isinstance(servers, dict):
        servers = {}
        mcp_block["servers"] = servers
    if servers.get(section) == entry:
        return False
    servers[section] = entry
    if dry_run:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _codex_section_re(section: str) -> re.Pattern[str]:
    return re.compile(rf"(?ms)^\[mcp_servers\.{re.escape(section)}\]\n.*?(?=^\[|\Z)")


def _write_codex_toml(path: Path, url: str, section: str = "elliot", dry_run: bool = False) -> bool:
    """Write [mcp_servers.<section>] into a Codex config.toml. Returns True if changed.

    When ``dry_run`` is set, nothing is written.
    """
    desired = f'[mcp_servers.{section}]\nurl = "{url}"\n'
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if desired in existing:
        return False
    section_re = _codex_section_re(section)
    if section_re.search(existing):
        new_content = section_re.sub(desired, existing, count=1)
    else:
        sep = "\n" if existing and not existing.endswith("\n") else ""
        gap = "\n" if existing else ""
        new_content = existing + sep + gap + desired
    if dry_run:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_content, encoding="utf-8")
    return True


def _probe_mcp_initialize(url: str, timeout: float = 2.0) -> tuple[bool, str | None]:
    """POST a JSON-RPC `initialize` and confirm a JSON-RPC reply.

    Returns (ok, reason). Used to verify a URL is actually MCP-speakable
    before we write it into an agent's config.
    """
    import json as _json
    import urllib.error
    import urllib.request

    body = _json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "elliot-connect-probe", "version": "0.1.0"},
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        # nosec - URL is operator-supplied (resolved from ELLIOT_*_URL env or
        # the local default). The CLI legitimately probes localhost, so this
        # path bypasses the SSRF validator.
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read(8192).decode("utf-8", errors="replace")
            if "jsonrpc" in raw or resp.status in (200, 202):
                return True, None
            return False, f"non-MCP response: HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        # FastMCP returns 400 on a probe-without-sessionid; that still proves
        # the endpoint is MCP-speaking, just rejecting the probe payload.
        if exc.code in (400, 405):
            return True, None
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        return False, str(exc)


def _register_for_all_agents(
    label: str,
    mcp_url: str,
    cwd: Path,
    home: Path,
    dry_run: bool = False,
) -> list[tuple[str, Path, str]]:
    """Write `mcp_url` (under the given label/section name) to every detected agent.

    When ``dry_run`` is set, no files are written and the reported status is
    "would update" instead of "updated".
    """
    results: list[tuple[str, Path, str]] = []
    section_key = f"elliot-{label}" if label != "plugin" else "elliot"
    changed_status = "would update" if dry_run else "updated"

    claude_config = cwd / ".mcp.json"
    changed = _write_json_merge(
        claude_config, "mcpServers", section_key, {"type": "http", "url": mcp_url}, dry_run=dry_run
    )
    results.append(
        ("Claude Code", claude_config, changed_status if changed else "already configured")
    )

    if shutil.which("cursor") or (home / ".cursor").exists() or (cwd / ".cursor").exists():
        cursor_config = cwd / ".cursor" / "mcp.json"
        changed = _write_json_merge(
            cursor_config,
            "mcpServers",
            section_key,
            {"type": "http", "url": mcp_url},
            dry_run=dry_run,
        )
        results.append(
            ("Cursor", cursor_config, changed_status if changed else "already configured")
        )

    if shutil.which("openclaw") or (home / ".openclaw").exists():
        openclaw_config = home / ".openclaw" / "openclaw.json"
        changed = _write_openclaw_json(openclaw_config, section_key, mcp_url, dry_run=dry_run)
        results.append(
            ("OpenClaw", openclaw_config, changed_status if changed else "already configured")
        )

    if shutil.which("codex") or (home / ".codex").exists() or (cwd / ".codex").exists():
        codex_config = cwd / ".codex" / "config.toml"
        changed = _write_codex_toml(codex_config, mcp_url, section=section_key, dry_run=dry_run)
        results.append(("Codex", codex_config, changed_status if changed else "already configured"))

    return results


def _cmd_connect(args: argparse.Namespace) -> None:
    """Register Elliot MCP server with every AI coding agent found on this machine.

    By default registers the *plugin* (build connectors, port 3000). Pass
    `--runtime` to also/instead register the *runtime* (serve a built
    connector to client agents, port 3001 by default). When the runtime is
    being registered, the URL is probed with a real MCP `initialize` first
    so we never write a config that points at a dead endpoint.
    """
    cwd = Path.cwd()
    home = Path.home()
    dry_run = getattr(args, "dry_run", False)
    plugin_url = os.environ.get("ELLIOT_PLUGIN_URL", "http://localhost:3000")
    runtime_url = os.environ.get("ELLIOT_RUNTIME_URL", "http://localhost:3001")

    # Trailing slash matters: strict MCP clients (Codex/rmcp) drop POST bodies
    # on 307 redirects. The runtime serves at /mcp/ without redirect.
    plugin_mcp = f"{plugin_url.rstrip('/')}/mcp/"
    runtime_mcp = f"{runtime_url.rstrip('/')}/mcp/"

    targets: list[tuple[str, str]] = []
    if getattr(args, "runtime_only", False):
        targets.append(("runtime", runtime_mcp))
    else:
        targets.append(("plugin", plugin_mcp))
        if getattr(args, "runtime", False):
            targets.append(("runtime", runtime_mcp))

    print("\nElliot MCP Connect")
    print("─" * 60)
    if dry_run:
        print("  (dry run — no files will be written)")

    any_registered = False
    for label, mcp_url in targets:
        print(f"\n  {label.title()} MCP: {mcp_url}")
        if label == "runtime":
            ok, reason = _probe_mcp_initialize(mcp_url)
            if not ok:
                print(f"  ✗ Skipped — runtime not reachable: {reason}")
                print("    Tip: build + export a connector, then call elliot_start_runtime.")
                continue
            print("  ✓ Verified MCP initialize handshake")

        results = _register_for_all_agents(label, mcp_url, cwd, home, dry_run=dry_run)
        if not results:
            print("  No supported agents detected on this machine.")
            print("  Supported: Claude Code, Cursor, OpenClaw, Codex")
            continue
        any_registered = True
        for agent, path, status in results:
            icon = "✓" if "configured" in status else "+"
            print(f"  {icon} {agent:<22} {status}")
            print(f"    └ {path}")

    if not any_registered:
        print()
        return

    print()
    print("  Next steps:")
    print("  1. Start Elliot:          make dev")
    print("  2. Reload your agent      (restart or run /reconnect-mcp)")
    print("  3. Ask your agent:        'I have an API at https://... — help me build a connector'")
    print()


def _cmd_kpi(args: argparse.Namespace) -> None:
    """Print the weekly PMF brief defined in SCOPE.md.

    Pulls retention, Sean Ellis distribution, and per-tool success rate from
    the observation store and reports against the three evidence gates we
    track before declaring product-market fit.
    """
    db_url = os.environ.get("ELLIOT_DB_URL", "sqlite:///.elliot/observations.db")

    try:
        from elliot_connector_runtime.observation_store import ObservationStore
        from elliot_connector_runtime.pmf import kpi_brief
    except ImportError as exc:
        print(f"elliot-connector-runtime is not installed: {exc}", file=sys.stderr)
        sys.exit(2)

    store = ObservationStore(db_url)
    brief = kpi_brief(store, window_days=args.window)

    if args.json:
        print(json.dumps(brief, indent=2, default=str))
        return

    r = brief["retention"]
    s = brief["sean_ellis"]
    gates = brief["gates"]

    print()
    print(f"Elliot KPI brief — last {brief['window_days']} days")
    print("─" * 56)
    print()
    print("Retention")
    print(f"  active installations:     {r['active_installations']}")
    print(f"  active on 2+ days:        {r['repeat_installations']}")
    print(f"  active agents (client+model): {r['active_agents']}")
    print(f"  median active days:       {r['active_days_median']:.1f}")
    print(f"  total sessions:           {r['total_sessions']}")
    print(f"  total tool calls:         {r['total_tool_calls']}")
    print(f"  error rate:               {r['error_rate']:.1%}")
    print()
    print(f"Sean Ellis (last {s['window_days']} days)")
    print(f"  responses:                {s['responses']}")
    print(f"  very disappointed:        {s['very_disappointed']}")
    print(f"  somewhat disappointed:    {s['somewhat_disappointed']}")
    print(f"  not disappointed:         {s['not_disappointed']}")
    print(f"  share very disappointed:  {s['very_disappointed_share']:.0%}")
    print()
    print("Tool success rate")
    tools = brief["tools"]
    if not tools:
        print("  (no tools with 20+ calls in the window)")
    else:
        for t in tools[:10]:
            print(f"  {t['tool_id']:<32} {t['calls']:>5} calls   {t['success_rate']:.0%} success")
    print(f"  median success rate:      {brief['median_tool_success_rate']:.0%}")
    print()
    print("Evidence gates (SCOPE.md §4)")
    for label, key in [
        ("≥10 repeat installations", "active_installations_ge_10"),
        ("Sean Ellis ≥40%", "sean_ellis_ge_40pct"),
        ("median success ≥90%", "median_success_ge_90pct"),
    ]:
        icon = "✓" if gates[key] else "✗"
        print(f"  {icon} {label}")
    print()
    if brief["pmf_reached"]:
        print("  All gates met. PMF threshold reached — see SCOPE.md §4.")
    else:
        print("  PMF not yet reached. Keep going; do not expand scope.")
    print()


def _cmd_trace(args: argparse.Namespace) -> None:
    """Install/remove the harness hook that streams local agent runs to Elliot."""
    from elliot_core.trace import SUPPORTED_HARNESSES
    from elliot_core.trace.installer import default_settings_path, install, uninstall

    harness = args.harness
    if harness not in SUPPORTED_HARNESSES:
        print(f"Unknown harness '{harness}'. Choose from: {', '.join(SUPPORTED_HARNESSES)}")
        sys.exit(1)

    if args.action == "install":
        path = install(harness)
        print(f"✓ Elliot trace hook installed for {harness}")
        print(f"  Config: {path}")
        print("  Restart the agent — its tool calls, prompt and reasoning will")
        print("  now appear in the Studio Agent Console while it works locally.")
    else:
        path = uninstall(harness)
        target = path if path.exists() else default_settings_path(harness)
        print(f"✓ Elliot trace hook removed for {harness} ({target})")


def main() -> None:
    # Windows consoles default to cp1252, which cannot encode the box-drawing
    # rules and check-mark glyphs (U+2500, U+2713, U+2717, U+2514) used in
    # `connect`/`status`/`scan` output — printing them raises UnicodeEncodeError
    # and crashes the command. Force UTF-8 on the standard streams so the CLI
    # behaves the same everywhere; errors="replace" keeps output flowing if a
    # stream still can't encode a glyph.
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                _reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="elliot", description="Elliot developer tools")
    sub = parser.add_subparsers(dest="command")

    lint_cmd = sub.add_parser("lint", help="Check a connector file for agent-readiness")
    lint_cmd.add_argument("path", help="Path to .connector.json")

    scan_cmd = sub.add_parser(
        "scan", help="Aggregate lint + quality analysis into one readiness report"
    )
    scan_cmd.add_argument("path", help="Path to .connector.json")

    eval_cmd = sub.add_parser("eval", help="Run evaluation cases against a connector")
    eval_cmd.add_argument("path", help="Path to .eval.yaml")
    eval_cmd.add_argument("--connector", help="Override connector .json path")

    init_cmd = sub.add_parser("init", help="Create a connector from a starter template")
    init_cmd.add_argument("template", nargs="?", help="Template name (see --list)")
    init_cmd.add_argument(
        "output", nargs="?", help="Output filename (default: <template>.connector.json)"
    )
    # Keep the original --template flag working so existing scripts and docs
    # (elliot init --template NAME OUT) don't break; the bare positional form
    # (elliot init NAME OUT) is now the documented one.
    init_cmd.add_argument("--template", dest="template_opt", help=argparse.SUPPRESS)
    init_cmd.add_argument("--list", action="store_true", help="Show available templates")

    export_cmd = sub.add_parser(
        "export-plugin",
        help="Scaffold an installable Codex + Claude Code plugin from a connector",
    )
    export_cmd.add_argument("path", help="Path to .connector.json")
    export_cmd.add_argument("--out", help="Output directory (default: <slug>-plugin/)")
    export_cmd.add_argument(
        "--force", action="store_true", help="Overwrite a non-empty output directory"
    )

    sub.add_parser("status", help="Show running status of all Elliot services")
    connect_cmd = sub.add_parser(
        "connect",
        help="Register Elliot MCP server with Claude Code, Cursor, VS Code, Windsurf, and Codex",
    )
    connect_cmd.add_argument(
        "--runtime",
        action="store_true",
        help=(
            "Also register the runtime URL (the connector served to client "
            "agents on port 3001). Probed with a real MCP initialize before "
            "writing — skipped if the runtime is not reachable."
        ),
    )
    connect_cmd.add_argument(
        "--runtime-only",
        action="store_true",
        dest="runtime_only",
        help="Register only the runtime URL (skip the plugin URL).",
    )
    connect_cmd.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Preview which agent config files would change, without writing anything.",
    )

    kpi_cmd = sub.add_parser(
        "kpi",
        help="Weekly PMF brief — retention, Sean Ellis, success rate (SCOPE.md §4)",
    )
    kpi_cmd.add_argument("--window", type=int, default=14, help="Window size in days (default: 14)")
    kpi_cmd.add_argument(
        "--json", action="store_true", help="Output the brief as JSON instead of text"
    )

    trace_cmd = sub.add_parser(
        "trace",
        help="Install hooks so a local agent's runs show in the Agent Console",
    )
    trace_cmd.add_argument(
        "action", choices=["install", "uninstall"], help="Install or remove the trace hook"
    )
    trace_cmd.add_argument(
        "--harness",
        required=True,
        choices=["claude-code", "codex", "cursor"],
        help="Which coding agent to wire up",
    )

    args = parser.parse_args()

    if args.command == "lint":
        _cmd_lint(args)
    elif args.command == "scan":
        _cmd_scan(args)
    elif args.command == "eval":
        _cmd_eval(args)
    elif args.command == "init":
        _cmd_init(args)
    elif args.command == "export-plugin":
        _cmd_export_plugin(args)
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "connect":
        _cmd_connect(args)
    elif args.command == "kpi":
        _cmd_kpi(args)
    elif args.command == "trace":
        _cmd_trace(args)
    else:
        parser.print_help()
        sys.exit(1)
