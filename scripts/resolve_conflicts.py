#!/usr/bin/env python3
"""Resolve sync conflicts by taking the upstream side — behind `/rhiza:update` step 6.

`scripts/sync.py` exits **1** when a template change collides with a local edit, leaving
`<<<<<<< ======= >>>>>>>` markers and possibly `*.rej` files. `/update`'s policy is to
take the **upstream** side everywhere: a rhiza-managed file is the template's to own, and
local divergence in one is drift to be undone, not work to preserve.

That policy was prose, which is the wrong home for text surgery. Conflict resolution is
the one step that **rewrites files the user did not author** — a marker left behind ships
`<<<<<<<` into a repo, and a mis-parsed block silently discards upstream's change. Prose
also cannot be tested: nothing executes it, so the documented procedure had no coverage
at all beyond `scan_conflict_artifacts` unit tests.

Scope, deliberately narrow:

* **Conflict markers are resolved.** Each ``<<<<<<< … ======= … >>>>>>>`` block is
  replaced by its *theirs* section. Nested or malformed blocks are refused rather than
  guessed at.
* **A `*.rej` beside a file we just resolved is *superseded*, and is deleted.** This is
  the case the prose got wrong. `sync.py` tries ``git apply -3`` first and falls back to
  ``git merge-file``, so a single collision leaves *both* artifacts describing the *same*
  change: markers holding the upstream side, and a reject holding the identical hunk.
  Taking the upstream side already applies it — "apply its hunks, then delete the .rej"
  would apply it twice.
* **Any other `*.rej` is reported, never applied.** A reject with no resolved counterpart
  holds a hunk git could not place at all, and re-deriving where it belongs is exactly
  the judgement that corrupts files. Exiting non-zero keeps the caller honest.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/resolve_conflicts.py [TARGET] [--dry-run] [--json]

Exit codes:
  0  no conflicts, or every marker resolved and no rejects remain
  1  `*.rej` files remain — they need a human
  2  a malformed conflict block was found and nothing was written
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

OURS = "<<<<<<<"
SEPARATOR = "======="
THEIRS = ">>>>>>>"

EXIT_OK = 0
EXIT_REJECTS_REMAIN = 1
EXIT_MALFORMED = 2

# Binary and vendored trees are never conflict-resolved by hand.
_SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv"})


class MalformedConflict(Exception):
    """A conflict block that cannot be resolved without guessing."""


def take_theirs(text: str) -> tuple[str, int]:
    """Replace every conflict block in *text* with its upstream side.

    Returns ``(resolved_text, blocks_resolved)``. Raises :class:`MalformedConflict` when
    a block is unterminated or the markers are out of order — the caller must see that
    rather than receive a plausible-looking file.
    """
    out: list[str] = []
    resolved = 0
    theirs: list[str] | None = None
    state = "copy"  # copy -> ours -> theirs

    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        marker = line.split(" ", 1)[0].rstrip("\r\n")
        if state == "copy":
            if marker == OURS:
                state, theirs = "ours", []
            elif marker in (SEPARATOR, THEIRS):
                raise MalformedConflict(f"line {number}: {marker!r} outside a conflict block")
            else:
                out.append(line)
        elif state == "ours":
            if marker == SEPARATOR:
                state = "theirs"
            elif marker == OURS:
                raise MalformedConflict(f"line {number}: nested conflict block")
            # Anything else is our side, which is discarded.
        else:  # theirs
            if marker == THEIRS:
                assert theirs is not None
                out.extend(theirs)
                resolved += 1
                state, theirs = "copy", None
            elif marker in (OURS, SEPARATOR):
                raise MalformedConflict(f"line {number}: {marker!r} inside the upstream side")
            else:
                assert theirs is not None
                theirs.append(line)

    if state != "copy":
        raise MalformedConflict("unterminated conflict block at end of file")
    return "".join(out), resolved


def _walk(target: Path) -> list[Path]:
    """Return the candidate files under *target*, skipping vendored trees."""
    found = []
    for path in sorted(target.rglob("*")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file():
            found.append(path)
    return found


def find_conflicts(target: Path) -> tuple[list[Path], list[Path]]:
    """Return ``(files_with_markers, reject_files)`` under *target*."""
    marked: list[Path] = []
    rejects: list[Path] = []
    for path in _walk(target):
        if path.suffix == ".rej":
            rejects.append(path)
            continue
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable: never a text conflict
        if any(line.startswith(OURS) for line in text.splitlines()):
            marked.append(path)
    return marked, rejects


def resolve(target: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Take the upstream side throughout *target*; return a summary dict."""
    marked, rejects = find_conflicts(target)
    resolved: list[dict[str, Any]] = []

    for path in marked:
        original = path.read_text()
        try:
            new_text, blocks = take_theirs(original)
        except MalformedConflict as exc:
            return {
                "resolved": [],
                "superseded": [],
                "rejects": [str(p.relative_to(target)) for p in rejects],
                "notes": [f"{path.relative_to(target)}: {exc} — nothing was written"],
                "exit_code": EXIT_MALFORMED,
            }
        if not dry_run:
            path.write_text(new_text)
        resolved.append({"path": str(path.relative_to(target)), "blocks": blocks})

    # A reject beside a file we just resolved describes the same change the upstream
    # side already carried, because sync.py tries `git apply -3` before falling back to
    # `git merge-file`. Applying it again would duplicate the hunk.
    resolved_paths = {entry["path"] for entry in resolved}
    superseded: list[str] = []
    outstanding: list[str] = []
    for path in rejects:
        rel = str(path.relative_to(target))
        if rel[: -len(".rej")] in resolved_paths:
            superseded.append(rel)
            if not dry_run:
                path.unlink()
        else:
            outstanding.append(rel)

    notes: list[str] = []
    if dry_run and (resolved or superseded):
        notes.append("dry run — nothing was written or deleted")
    if superseded:
        notes.append(
            f"{len(superseded)} .rej file(s) superseded by the resolved markers and removed — "
            "the same hunk, already taken from upstream"
        )
    if outstanding:
        notes.append(
            f"{len(outstanding)} .rej file(s) remain with no resolved counterpart. They hold "
            "hunks git could not place, and re-deriving where they belong is how files get "
            "corrupted. Apply them by hand, then delete the .rej."
        )
    if not marked and not rejects:
        notes.append("no conflicts found")

    return {
        "resolved": resolved,
        "superseded": superseded,
        "rejects": outstanding,
        "notes": notes,
        "exit_code": EXIT_REJECTS_REMAIN if outstanding else EXIT_OK,
    }


def main(argv: list[str] | None = None) -> int:
    """Entry point: resolve conflict markers and return an exit code."""
    parser = argparse.ArgumentParser(
        description="Resolve sync conflicts by taking the upstream side.",
    )
    parser.add_argument(
        "target", nargs="?", default=".", help="Repository root (default: current directory)."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would change, write nothing."
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    summary = resolve(Path(args.target).resolve(), dry_run=args.dry_run)

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        for entry in summary["resolved"]:
            print(f"resolved {entry['path']}: {entry['blocks']} block(s) -> upstream")
        for path in summary["superseded"]:
            print(f"removed  {path} (superseded by the resolved markers)")
        for path in summary["rejects"]:
            print(f"reject   {path}", file=sys.stderr)
        for note in summary["notes"]:
            stream = sys.stdout if summary["exit_code"] == EXIT_OK else sys.stderr
            print(f"note     {note}", file=stream)
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
