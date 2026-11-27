#!/usr/bin/env python3
"""Fail when any block under the scripts tree exceeds cyclomatic complexity 12.

CLAUDE.md states the bar as "no block above C(12)", and for its whole life the bar was a
report: `make complexity` prints what radon finds and exits 0, so a PR could add a C(17)
block and stay green. That happened three times — each found by a later `/rhiza:quality`
run, never by the PR that caused it. This is the gate that was missing.

**Why not xenon**, the usual thresholding wrapper: it thresholds on radon's *letter*
grades, and grade C spans complexity 11 to 20. "At most C" would let a 20 through, "at
most B" would fail on an 11 the bar allows. The bar is a number, so the check compares
numbers — radon still does the measuring, this only reads its JSON.

What counts as a block is radon's own list — functions, methods and classes — plus every
**closure**, which radon's text report hides by default. A closure is code someone has to
read under pressure like any other, and a bar that skipped it could be met by nesting.
Methods appear in radon's output twice (flat, and again under their class), so only the
flat list is walked.

A file radon cannot parse is a **failure**, not a skip. Radon reports it as an error entry
and still exits 0; passing over it would mean the gate went green on code it never
measured — the fail-open shape CLAUDE.md warns about for every gate scoped to this tree.

Radon is not imported — this tree is stdlib-only — but run through ``uvx``, inheriting
``UV_CONSTRAINT`` so `make fmt` measures with the version requirements-dev.txt pins, the
same one `make complexity` uses.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/check_complexity.py [--root plugin/scripts] [--max 12]

Exit codes:
  0  every block is at or under the ceiling
  1  a block exceeds it, or a file could not be measured
  2  radon itself could not be run
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404
import sys
from collections.abc import Iterator
from typing import Any

ROOT = "plugin/scripts"
"""Default tree to measure: the scope of the bar, not an example — ``tests/`` is exempt."""

CEILING = 12
"""The highest cyclomatic complexity a block may have."""


def _blocks(blocks: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Yield every block in radon's flat list, then each closure beneath it, recursively."""
    for block in blocks:
        yield block
        yield from _blocks(block.get("closures", []))


def violations(report: dict[str, Any], ceiling: int) -> list[str]:
    """Return one line per block over *ceiling*, and per file radon could not measure.

    >>> report = {"a.py": [
    ...     {"name": "f", "lineno": 3, "complexity": 13, "closures": [
    ...         {"name": "g", "lineno": 4, "complexity": 14, "closures": []}]},
    ...     {"name": "h", "lineno": 9, "complexity": 12, "closures": []}]}
    >>> violations(report, 12)
    ['a.py:3 f — complexity 13 (max 12)', 'a.py:4 g — complexity 14 (max 12)']
    >>> violations({"b.py": {"error": "invalid syntax"}}, 12)
    ['b.py — could not be measured: invalid syntax']
    >>> violations({"c.py": []}, 12)
    []
    """
    found: list[str] = []
    for path in sorted(report):
        entry = report[path]
        if isinstance(entry, dict):
            found.append(f"{path} — could not be measured: {entry.get('error', 'unknown error')}")
            continue
        for block in _blocks(entry):
            if block["complexity"] > ceiling:
                found.append(
                    f"{path}:{block['lineno']} {block['name']} — "
                    f"complexity {block['complexity']} (max {ceiling})"
                )
    return found


def measure(root: str) -> dict[str, Any] | None:
    """Run radon over *root* and return its JSON report, or None if radon failed."""
    uvx = shutil.which("uvx")
    if uvx is None:
        print("uvx not found on PATH; it is what runs radon.", file=sys.stderr)
        return None
    proc = subprocess.run(  # nosec B603
        [uvx, "radon", "cc", "--json", root],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(f"radon failed (exit {proc.returncode}): {proc.stderr.strip()}", file=sys.stderr)
        return None
    report: dict[str, Any] = json.loads(proc.stdout)
    return report


def main(argv: list[str] | None = None) -> int:
    """Measure the tree and report every block over the ceiling."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=ROOT, help=f"Tree to measure (default: {ROOT}).")
    parser.add_argument(
        "--max", type=int, default=CEILING, help=f"Highest allowed complexity (default: {CEILING})."
    )
    args = parser.parse_args(argv)

    report = measure(args.root)
    if report is None:
        return 2
    found = violations(report, args.max)
    for line in found:
        print(line)
    if found:
        print(
            f"{len(found)} block(s) over complexity {args.max} — split them rather than "
            "raising the ceiling.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
