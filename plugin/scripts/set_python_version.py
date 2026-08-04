#!/usr/bin/env python3
"""Set (or retarget) a project's standard Python version — behind `/rhiza:python-version`.

Edits ``pyproject.toml``'s ``[project]`` table: pins ``requires-python`` to
``>=X.Y`` and rewrites the ``Programming Language :: Python :: X.Y`` trove
classifiers to the supported range (dropping any stale Python classifiers,
including a bare ``... :: 3``, while preserving non-Python classifiers). Stdlib-only,
so `/init` and `/python-version` can run it without the `rhiza` CLI.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/set_python_version.py [TARGET] --python-version 3.12 [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_toml import rejoin, require_table  # noqa: E402

# Python minor versions we standardise on (oldest → newest).
KNOWN_PY_VERSIONS = ("3.11", "3.12", "3.13", "3.14")
_PY_CLASSIFIER = re.compile(r"^Programming Language :: Python :: 3(\.\d+)?$")


def python_version_classifiers(python_version: str) -> list[str]:
    """Concrete ``Programming Language :: Python :: X.Y`` classifiers from *python_version* up.

    Never the bare major-version ``... :: 3`` classifier, which modern tooling
    discourages.
    """
    if python_version not in KNOWN_PY_VERSIONS:
        raise ValueError(
            f"unknown python version {python_version!r}; choose from {', '.join(KNOWN_PY_VERSIONS)}"
        )
    start = KNOWN_PY_VERSIONS.index(python_version)
    return [f"Programming Language :: Python :: {v}" for v in KNOWN_PY_VERSIONS[start:]]


def _classifiers_span(lines: list[str], header: int, end: int) -> tuple[int, int] | None:
    """Return ``(start, stop)`` line indices of the ``classifiers = [...]`` array, or None."""
    for i in range(header + 1, end):
        if re.match(r"^\s*classifiers\s*=", lines[i]):
            if "]" in lines[i]:
                return i, i
            for j in range(i + 1, len(lines)):
                if lines[j].strip() == "]":
                    return i, j
            return i, i
    return None


def _classifiers_block(classifiers: list[str]) -> list[str]:
    """Render a ``classifiers = [...]`` array as the lines it occupies."""
    return ["classifiers = ["] + [f'    "{c}",' for c in classifiers] + ["]"]


def _apply_requires_python(lines: list[str], header: int, end: int, python_version: str) -> bool:
    """Pin ``requires-python`` in place, inserting it when absent; return whether it moved."""
    wanted = f'requires-python = ">={python_version}"'
    pattern = re.compile(r"^\s*requires-python\s*=")
    for i in range(header + 1, end):
        if not pattern.match(lines[i]):
            continue
        if lines[i] == wanted:
            return False
        lines[i] = wanted
        return True
    lines.insert(header + 1, wanted)
    return True


def _apply_classifiers(lines: list[str], header: int, end: int, wanted: list[str]) -> bool:
    """Merge *wanted* into ``[project].classifiers``; return whether anything changed.

    Non-Python classifiers are preserved and keep their order — only the
    ``Programming Language :: Python :: X.Y`` entries are swapped for the supported range,
    since those are the ones this script owns.
    """
    span = _classifiers_span(lines, header, end)
    if span is None:
        lines[header + 1 : header + 1] = _classifiers_block(wanted)
        return True

    start, stop = span
    existing = re.findall(r'"([^"]*)"', "\n".join(lines[start : stop + 1]))
    kept = [entry for entry in existing if not _PY_CLASSIFIER.match(entry)]
    # `dict.fromkeys` dedupes while preserving first-seen order.
    rebuilt = _classifiers_block(list(dict.fromkeys([*kept, *wanted])))
    if rebuilt == lines[start : stop + 1]:
        return False
    lines[start : stop + 1] = rebuilt
    return True


def apply_python_metadata(text: str, python_version: str) -> tuple[str, list[str]]:
    """Pin ``requires-python`` and rewrite Python version classifiers in ``[project]``.

    ``requires-python`` is corrected in place (inserted if absent); the Python
    version classifiers are replaced with the supported range while any other
    classifiers are preserved. Returns ``(new_text, changes)``.
    """
    lines = text.splitlines()
    changes: list[str] = []

    header, end = require_table(lines, "project", "pyproject.toml")
    if _apply_requires_python(lines, header, end, python_version):
        changes.append("requires-python")

    # Re-bound the table: inserting `requires-python` shifted every index after it.
    header, end = require_table(lines, "project", "pyproject.toml")
    if _apply_classifiers(lines, header, end, python_version_classifiers(python_version)):
        changes.append("classifiers")

    return rejoin(text, lines), changes


def set_python_version(target: Path, *, python_version: str) -> dict[str, Any]:
    """Retarget the repo at *target* to *python_version*; return a summary dict."""
    modified: list[str] = []
    notes: list[str] = []
    pyproject = target / "pyproject.toml"
    if not pyproject.exists():
        notes.append("pyproject.toml absent — nothing to retarget")
        return {"python_version": python_version, "modified": modified, "notes": notes}
    try:
        new_text, changes = apply_python_metadata(pyproject.read_text(), python_version)
    except ValueError as exc:
        notes.append(f"pyproject.toml: {exc}")
        return {"python_version": python_version, "modified": modified, "notes": notes}
    if changes:
        pyproject.write_text(new_text)
        modified.append("pyproject.toml")
        notes.append("pyproject.toml: " + ", ".join(changes))
    else:
        notes.append("already up to date")
    return {"python_version": python_version, "modified": modified, "notes": notes}


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, retarget, return an exit code."""
    parser = argparse.ArgumentParser(description="Set or retarget a project's Python version.")
    parser.add_argument(
        "target", nargs="?", default=".", help="Repository root (default: current directory)."
    )
    parser.add_argument(
        "--python-version",
        dest="python_version",
        required=True,
        help=f"Standard Python minor version ({', '.join(KNOWN_PY_VERSIONS)}).",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    if args.python_version not in KNOWN_PY_VERSIONS:
        parser.error(
            f"unknown --python-version {args.python_version!r}; "
            f"choose from {', '.join(KNOWN_PY_VERSIONS)}"
        )

    summary = set_python_version(Path(args.target).resolve(), python_version=args.python_version)

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        for path in summary["modified"]:
            print(f"modified {path}")
        for note in summary["notes"]:
            print(f"note     {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
