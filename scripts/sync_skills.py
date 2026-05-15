#!/usr/bin/env python3
"""Sync .claude-plugin/skills/ -> .codex-plugin/skills/.

The Claude Code plugin format and the Codex plugin format (launched Mar 2026)
both load skills from `skills/<name>/SKILL.md` with YAML frontmatter. To avoid
drift, we treat `.claude-plugin/skills/` as the canonical source and mirror it
into `.codex-plugin/skills/` on demand.

Usage:
    uv run python scripts/sync_skills.py          # sync (write)
    uv run python scripts/sync_skills.py --check  # verify in sync; exit 1 if not

CI / pre-push checks should run with `--check`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_SKILLS = REPO_ROOT / ".claude-plugin" / "skills"
CODEX_SKILLS = REPO_ROOT / ".codex-plugin" / "skills"


def _collect_skill_files(root: Path) -> dict[Path, bytes]:
    """Map every regular file under root to its bytes, keyed by relative path."""
    out: dict[Path, bytes] = {}
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if p.is_file():
            out[p.relative_to(root)] = p.read_bytes()
    return out


def _sync(write: bool) -> int:
    src = _collect_skill_files(CLAUDE_SKILLS)
    dst = _collect_skill_files(CODEX_SKILLS)

    to_write = {rel: data for rel, data in src.items() if dst.get(rel) != data}
    to_remove = [rel for rel in dst if rel not in src]

    if not write:
        if to_write or to_remove:
            print("OUT OF SYNC. Run: uv run python scripts/sync_skills.py")
            for rel in sorted(to_write):
                print(f"  needs write:  .codex-plugin/skills/{rel}")
            for rel in sorted(to_remove):
                print(f"  needs remove: .codex-plugin/skills/{rel}")
            return 1
        print("Codex skills mirror is in sync with Claude skills.")
        return 0

    for rel, data in to_write.items():
        target = CODEX_SKILLS / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"  wrote .codex-plugin/skills/{rel}")
    for rel in to_remove:
        target = CODEX_SKILLS / rel
        if target.exists():
            target.unlink()
            print(f"  removed .codex-plugin/skills/{rel}")
        # Prune empty parent dirs (best-effort, walks up)
        parent = target.parent
        while parent.is_dir() and parent != CODEX_SKILLS and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    # Also prune leaf dirs at the top level that ended up empty
    if CODEX_SKILLS.exists():
        for d in CODEX_SKILLS.iterdir():
            if d.is_dir() and not any(d.iterdir()):
                shutil.rmtree(d)

    if not to_write and not to_remove:
        print("Already in sync.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if .codex-plugin/skills/ is out of sync with .claude-plugin/skills/.",
    )
    args = parser.parse_args()
    sys.exit(_sync(write=not args.check))


if __name__ == "__main__":
    main()
