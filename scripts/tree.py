#!/usr/bin/env python3
"""List the files rhiza manages in this repo, as a directory tree.

A stdlib-only port of the `rhiza tree` command, bundled with this plugin so
`/rhiza:tree` works without the `rhiza` CLI (or PyYAML) installed. It reads the
`files` recorded in `.rhiza/template.lock` and prints them as a Unix-`tree`-style
view, then a total count.

Usage:
  python3 scripts/tree.py [TARGET]

  TARGET   repository root to inspect (default: current directory)

When no lock is present the repo has never been synced; this prints a hint to
stderr and exits 0 (nothing to show is not an error). Where the CLI uses `rich`
for the tree, this renders plain ASCII connectors so it stays dependency-free.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_yaml import load_yaml  # noqa: E402

LOCK_REL = Path(".rhiza") / "template.lock"


def _build_tree(paths: list[str]) -> dict[str, Any]:
    """Fold a flat path list into a nested {name: subtree} dict."""
    root: dict[str, Any] = {}
    for path in sorted(paths):
        node = root
        for part in Path(path).parts:
            node = node.setdefault(part, {})
    return root


def _render(node: dict[str, Any], prefix: str = "") -> list[str]:
    """Render a nested tree dict into Unix-`tree`-style lines."""
    lines: list[str] = []
    items = sorted(node.items())
    for i, (name, child) in enumerate(items):
        last = i == len(items) - 1
        lines.append(f"{prefix}{'└── ' if last else '├── '}{name}")
        if child:
            lines.extend(_render(child, prefix + ("    " if last else "│   ")))
    return lines


def tree(target: Path) -> int:
    """Print the managed-file tree; return a process exit code."""
    lock_path = (target / LOCK_REL).resolve()
    if not lock_path.exists():
        print("No template.lock found — run `rhiza sync` first", file=sys.stderr)
        return 0

    try:
        lock = load_yaml(lock_path)
    except (OSError, ValueError) as exc:
        print(f"Could not read {lock_path}: {exc}", file=sys.stderr)
        return 1

    files = [str(f) for f in (lock.get("files") or [])]
    if not files:
        print("No files are tracked in template.lock", file=sys.stderr)
        return 0

    print(".")
    for line in _render(_build_tree(files)):
        print(line)
    print(f"\n{len(files)} file{'s' if len(files) != 1 else ''} managed by Rhiza")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point: print the managed-file tree; return an exit code."""
    parser = argparse.ArgumentParser(
        description="List files managed by rhiza (from .rhiza/template.lock) as a tree.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Repository root to inspect (default: current directory).",
    )
    args = parser.parse_args(argv)
    return tree(Path(args.target))


if __name__ == "__main__":
    raise SystemExit(main())
