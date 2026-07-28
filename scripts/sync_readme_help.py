#!/usr/bin/env python3
"""Sync the README's `make help` block from live output — behind `/rhiza:docs`.

Keeps a README's list of `make` targets in lockstep with the actual `Makefile`, so
contributors never read a stale target list. Replaces the retired rhiza-tools
``update-readme`` command.

The contract is deliberately narrow, because this edits a file humans have written:

* it finds the marker line ``Run `make help` to see all available targets:`` and the
  fenced code block immediately after it, and replaces **only that block's
  contents** — the marker, the fences, and every other byte stay put;
* marker missing, or present with no following fence? **No-op**, reported as such.
  It never invents a place to put the list;
* ``make help`` output is sanitised first — help targets colourise names, and
  recursive makes emit ``Entering directory`` chatter — so the result is stable;
* it is **idempotent**: against an unchanged ``Makefile`` a second run writes
  nothing, which is what makes it safe to run on every `/rhiza:docs`.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/sync_readme_help.py [TARGET] [--readme README.md] [--json]

Exit codes:
  0  block refreshed, or already up to date, or nothing to do (no marker/Makefile)
  2  `make help` failed
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

MARKER = "Run `make help` to see all available targets:"
_FENCE = "```"
_MAKEFILES = ("Makefile", "makefile", "GNUmakefile")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_MAKE_CHATTER = re.compile(r"^make\[\d+\]: (Entering|Leaving) directory")

EXIT_OK = 0
EXIT_MAKE_FAILED = 2


def find_makefile(target: Path) -> Path | None:
    """Return the repo's makefile, or None when there isn't one."""
    return next((target / name for name in _MAKEFILES if (target / name).is_file()), None)


def has_help_target(makefile: Path) -> bool:
    """Is a ``help`` target (or a help default goal) declared in *makefile*?

    Only the root makefile is inspected: an included ``.mk`` may well define the
    target, which is why a false answer still leads to running ``make help`` being
    skipped rather than to an error.
    """
    text = makefile.read_text(errors="replace")
    return bool(re.search(r"^help:", text, re.MULTILINE)) or ".DEFAULT_GOAL := help" in text


def clean_help_output(raw: str) -> str:
    """Strip ANSI colour codes and recursive-make chatter from ``make help`` output."""
    lines = [_ANSI.sub("", line).rstrip() for line in raw.splitlines()]
    kept = [line for line in lines if not _MAKE_CHATTER.match(line)]
    while kept and not kept[0].strip():
        kept.pop(0)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)


def find_block(lines: list[str]) -> tuple[int, int] | None:
    """Return ``(first_content_idx, fence_close_idx)`` for the marker's fenced block.

    ``first_content_idx`` is the line after the opening fence, so an empty block
    yields a span where start == the closing fence index. Returns None when the
    marker is absent, or present with no fence following it.
    """
    marker = next((i for i, line in enumerate(lines) if MARKER in line), None)
    if marker is None:
        return None
    # The opening fence must follow the marker, allowing blank lines between.
    opening = None
    for i in range(marker + 1, len(lines)):
        if not lines[i].strip():
            continue
        opening = i if lines[i].lstrip().startswith(_FENCE) else None
        break
    if opening is None:
        return None
    for j in range(opening + 1, len(lines)):
        if lines[j].lstrip().startswith(_FENCE):
            return opening + 1, j
    return None


def sync_readme_help(target: Path, readme_name: str = "README.md") -> dict[str, Any]:
    """Refresh the README's `make help` block at *target*; return a summary dict."""
    readme = target / readme_name

    if not readme.is_file():
        return _result("skipped", f"no {readme_name}")

    makefile = find_makefile(target)
    if makefile is None:
        return _result("skipped", "no Makefile")
    if not has_help_target(makefile):
        return _result("skipped", "Makefile has no `help` target")

    original = readme.read_text()
    span = find_block(original.splitlines())
    if span is None:
        return _result("skipped", f"no `{MARKER}` marker with a following fenced block")

    make = shutil.which("make")
    if make is None:
        return _result("skipped", "make is not on PATH")
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    proc = subprocess.run(  # nosec B603
        [make, "help"], cwd=str(target), capture_output=True, text=True, env=env, check=False
    )
    if proc.returncode != 0:
        return {
            "status": "failed",
            "note": f"`make help` failed: {proc.stderr.strip()[:200]}",
            "exit_code": EXIT_MAKE_FAILED,
        }

    body = clean_help_output(proc.stdout)
    lines = original.splitlines()
    start, close = span
    if lines[start:close] == body.splitlines():
        return _result("unchanged", "the target list already matches `make help`")

    lines[start:close] = body.splitlines()
    updated = "\n".join(lines)
    if original.endswith("\n"):
        updated += "\n"
    readme.write_text(updated)
    return _result("refreshed", f"{len(body.splitlines())} line(s) from `make help`")


def _result(status: str, note: str) -> dict[str, Any]:
    """Build a summary dict for a non-failure outcome."""
    return {"status": status, "note": note, "exit_code": EXIT_OK}


def main(argv: list[str] | None = None) -> int:
    """Entry point: sync the README block and return an exit code."""
    parser = argparse.ArgumentParser(description="Sync a README's `make help` block.")
    parser.add_argument(
        "target", nargs="?", default=".", help="Repository root (default: current directory)."
    )
    parser.add_argument("--readme", default="README.md", help="README filename.")
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    summary = sync_readme_help(Path(args.target).resolve(), args.readme)

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        stream = sys.stderr if summary["status"] in ("skipped", "failed") else sys.stdout
        print(f"{summary['status']:<10} {summary['note']}", file=stream)
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
