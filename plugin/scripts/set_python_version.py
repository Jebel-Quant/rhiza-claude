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


def _project_block(lines: list[str]) -> tuple[int, int]:
    """Return ``(header_idx, end_idx)`` bounding the ``[project]`` table body."""
    header = next((i for i, line in enumerate(lines) if line.strip() == "[project]"), None)
    if header is None:
        raise ValueError("pyproject.toml has no [project] table")
    end = len(lines)
    for i in range(header + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            end = i
            break
    return header, end


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


def apply_python_metadata(text: str, python_version: str) -> tuple[str, list[str]]:
    """Pin ``requires-python`` and rewrite Python version classifiers in ``[project]``.

    ``requires-python`` is corrected in place (inserted if absent); the Python
    version classifiers are replaced with the supported range while any other
    classifiers are preserved. Returns ``(new_text, changes)``.
    """
    new_classifiers = python_version_classifiers(python_version)
    lines = text.splitlines()
    header, end = _project_block(lines)
    changes: list[str] = []

    # requires-python — replace in place, else insert.
    rp_line = f'requires-python = ">={python_version}"'
    rp_pat = re.compile(r"^\s*requires-python\s*=")
    for i in range(header + 1, end):
        if rp_pat.match(lines[i]):
            if lines[i] != rp_line:
                lines[i] = rp_line
                changes.append("requires-python")
            break
    else:
        lines.insert(header + 1, rp_line)
        changes.append("requires-python")

    # classifiers — merge: keep non-Python entries, swap in the new Python range.
    header, end = _project_block(lines)
    span = _classifiers_span(lines, header, end)
    if span is None:
        block = ["classifiers = ["] + [f'    "{c}",' for c in new_classifiers] + ["]"]
        lines[header + 1 : header + 1] = block
        changes.append("classifiers")
    else:
        start, stop = span
        existing = re.findall(r'"([^"]*)"', "\n".join(lines[start : stop + 1]))
        kept = [e for e in existing if not _PY_CLASSIFIER.match(e)]
        merged: list[str] = []
        for entry in [*kept, *new_classifiers]:
            if entry not in merged:
                merged.append(entry)
        rebuilt = ["classifiers = ["] + [f'    "{c}",' for c in merged] + ["]"]
        if rebuilt != lines[start : stop + 1]:
            lines[start : stop + 1] = rebuilt
            changes.append("classifiers")

    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    return new_text, changes


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
