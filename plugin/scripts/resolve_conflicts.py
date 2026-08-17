#!/usr/bin/env python3
"""Resolve sync conflicts by taking the upstream side — behind `/rhiza:update` step 6.

`scripts/sync.py` exits **1** when a template change collides with a local edit, leaving
`<<<<<<< ======= >>>>>>>` markers. `/update`'s policy is to
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
* **`*.rej` files are reported, never applied.** Re-deriving where an unplaceable hunk
  belongs is exactly the judgement that corrupts files, so this exits non-zero and leaves
  it to a human.

  The sync no longer produces rejects at all: ``git apply --reject`` was the only thing
  that ever created one, and `_rhiza_merge.py` replaced the whole ``git apply`` path. An
  earlier version of this script *deleted* a reject sitting beside a file it had just
  resolved, on the sound reasoning that `sync.py` then emitted both artifacts for one
  collision — markers plus the identical hunk — so applying the reject too would apply
  the change twice. That cause is gone, and with it the justification: a reject found
  today came from an older sync or a hand-run ``git apply``, and deleting it because we
  happened to resolve markers in the same file would be a guess about contents nobody
  checked.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/resolve_conflicts.py [TARGET] [--dry-run] [--json]

Exit codes:
  0  no conflicts, or every marker resolved and no rejects remain
  1  `*.rej` files remain — they need a human (the sync cannot create these)
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


def _outside_block(marker: str, line: str, number: int, out: list[str]) -> bool:
    """Handle a line outside any conflict block; return whether a block just opened.

    A separator or closing marker out here means the file's markers are out of order,
    which is exactly the case that must not be guessed at.
    """
    if marker == OURS:
        return True
    if marker in (SEPARATOR, THEIRS):
        raise MalformedConflict(f"line {number}: {marker!r} outside a conflict block")
    out.append(line)
    return False


def _our_side(marker: str, number: int) -> bool:
    """Handle a line on our side; return whether the separator was reached.

    The line itself is dropped either way — taking upstream means our side is discarded.
    """
    if marker == SEPARATOR:
        return True
    if marker == OURS:
        raise MalformedConflict(f"line {number}: nested conflict block")
    return False


def _their_side(marker: str, line: str, number: int, theirs: list[str]) -> bool:
    """Collect a line on the upstream side; return whether the block just closed."""
    if marker == THEIRS:
        return True
    if marker in (OURS, SEPARATOR):
        raise MalformedConflict(f"line {number}: {marker!r} inside the upstream side")
    theirs.append(line)
    return False


def take_theirs(text: str) -> tuple[str, int]:
    """Replace every conflict block in *text* with its upstream side.

    A three-state machine — copy → ours → theirs — with one handler per state, each
    returning whether the state it was given has ended. Returns
    ``(resolved_text, blocks_resolved)``. Raises :class:`MalformedConflict` when a block is
    unterminated or the markers are out of order: the caller must see that rather than
    receive a plausible-looking file.
    """
    out: list[str] = []
    theirs: list[str] = []
    resolved = 0
    state = "copy"

    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        marker = line.split(" ", 1)[0].rstrip("\r\n")
        if state == "copy":
            if _outside_block(marker, line, number, out):
                state, theirs = "ours", []
        elif state == "ours":
            if _our_side(marker, number):
                state = "theirs"
        elif _their_side(marker, line, number, theirs):
            out.extend(theirs)
            resolved += 1
            state, theirs = "copy", []

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
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable: never a text conflict
        if any(line.startswith(OURS) for line in text.splitlines()):
            marked.append(path)
    return marked, rejects


def _resolve_notes(
    marked: list[Path],
    rejects: list[Path],
    outstanding: list[str],
    resolved: list[dict[str, Any]],
    *,
    dry_run: bool,
) -> list[str]:
    """Build the notes for a completed resolve pass."""
    notes: list[str] = []
    if dry_run and resolved:
        notes.append("dry run — nothing was written")
    if outstanding:
        notes.append(
            f"{len(outstanding)} .rej file(s) remain. The sync no longer creates these — "
            "`git apply --reject` was the only thing that ever did, and it is gone — so one "
            "here came from an older sync or a hand-run `git apply`, and its contents cannot "
            "be assumed redundant. Apply them by hand, then delete the .rej."
        )
    if not marked and not rejects:
        notes.append("no conflicts found")
    return notes


def resolve(target: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Take the upstream side throughout *target*; return a summary dict."""
    marked, rejects = find_conflicts(target)
    resolved: list[dict[str, Any]] = []

    for path in marked:
        original = path.read_text(encoding="utf-8")
        try:
            new_text, blocks = take_theirs(original)
        except MalformedConflict as exc:
            return {
                "resolved": [],
                "rejects": [p.relative_to(target).as_posix() for p in rejects],
                "notes": [f"{path.relative_to(target).as_posix()}: {exc} — nothing was written"],
                "exit_code": EXIT_MALFORMED,
            }
        if not dry_run:
            path.write_text(new_text, encoding="utf-8")
        resolved.append({"path": path.relative_to(target).as_posix(), "blocks": blocks})

    outstanding = [path.relative_to(target).as_posix() for path in rejects]

    return {
        "resolved": resolved,
        "rejects": outstanding,
        "notes": _resolve_notes(marked, rejects, outstanding, resolved, dry_run=dry_run),
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
        for path in summary["rejects"]:
            print(f"reject   {path}", file=sys.stderr)
        for note in summary["notes"]:
            stream = sys.stdout if summary["exit_code"] == EXIT_OK else sys.stderr
            print(f"note     {note}", file=stream)
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
