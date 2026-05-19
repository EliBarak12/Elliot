#!/usr/bin/env python3
"""Sync .claude-plugin/skills/ -> .codex-plugin/skills/ and .cursor-plugin/skills/.

The Claude Code, Codex, and Cursor plugin formats all load skills from
`skills/<name>/SKILL.md` with YAML frontmatter. To avoid drift, we treat
`.claude-plugin/skills/` as the canonical source and mirror it into every
other plugin variant on demand.

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
# Every plugin variant the canonical Claude skills are mirrored into.
MIRROR_SKILLS = [
    REPO_ROOT / ".codex-plugin" / "skills",
    REPO_ROOT / ".cursor-plugin" / "skills",
]


def _collect_skill_files(root: Path) -> dict[Path, bytes]:
    """Map every regular file under root to its bytes, keyed by relative path."""
    out: dict[Path, bytes] = {}
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if p.is_file():
            out[p.relative_to(root)] = p.read_bytes()
    return out


def _sync_one(src: dict[Path, bytes], dst_root: Path, write: bool) -> tuple[int, int]:
    """Sync one mirror target. Returns (files_written, files_removed); in
    --check mode the counts report what *would* change."""
    rel_label = dst_root.relative_to(REPO_ROOT)
    dst = _collect_skill_files(dst_root)
    to_write = {rel: data for rel, data in src.items() if dst.get(rel) != data}
    to_remove = [rel for rel in dst if rel not in src]

    if not write:
        for rel in sorted(to_write):
            print(f"  needs write:  {rel_label / rel}")
        for rel in sorted(to_remove):
            print(f"  needs remove: {rel_label / rel}")
        return len(to_write), len(to_remove)

    for rel, data in to_write.items():
        target = dst_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"  wrote {rel_label / rel}")
    for rel in to_remove:
        target = dst_root / rel
        if target.exists():
            target.unlink()
            print(f"  removed {rel_label / rel}")
        # Prune empty parent dirs (best-effort, walks up).
        parent = target.parent
        while parent.is_dir() and parent != dst_root and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    # Also prune leaf dirs at the top level that ended up empty.
    if dst_root.exists():
        for d in dst_root.iterdir():
            if d.is_dir() and not any(d.iterdir()):
                shutil.rmtree(d)

    return len(to_write), len(to_remove)


def _sync(write: bool) -> int:
    src = _collect_skill_files(CLAUDE_SKILLS)
    total_changes = 0
    for dst_root in MIRROR_SKILLS:
        written, removed = _sync_one(src, dst_root, write)
        total_changes += written + removed

    if not write:
        if total_changes:
            print("OUT OF SYNC. Run: uv run python scripts/sync_skills.py")
            return 1
        print("All plugin skill mirrors are in sync with Claude skills.")
        return 0

    if not total_changes:
        print("Already in sync.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any plugin skills mirror is out of sync with .claude-plugin/skills/.",
    )
    args = parser.parse_args()
    sys.exit(_sync(write=not args.check))


if __name__ == "__main__":
    main()
