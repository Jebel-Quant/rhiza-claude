#!/usr/bin/env python3
"""Scaffold a new source module and its mirrored test file.

Bundled with this plugin so `/rhiza:new` can add a module to a rhiza-managed
Python repo while keeping the test/source layout parity that
`scripts/check_test_layout.py` enforces: a source module ``src/<pkg>/…/xyz.py``
gets a matching ``tests/…/test_xyz.py``, and every ``class Foo`` gets a matching
``TestFoo`` in that test file. Generated stubs carry docstrings so the
interrogate gate stays at 100%.

Usage:
  uv run --python 3.12 --no-project python scripts/new_module.py NAME [TARGET] [--class CLASS] \
      [--src DIR] [--tests DIR] [--json]

  NAME      module name, optionally dotted/slashed for a subpackage
            (e.g. `parsing` or `utils.parsing` or `utils/parsing`)
  TARGET    repository root (default: current directory)
  --class   also scaffold a `class CLASS` in the module and a `TestCLASS`
            in the test file (repeatable)
  --src     source root, relative to TARGET (default: src)
  --tests   tests root, relative to TARGET (default: tests)
  --json    emit a JSON report instead of human-readable lines

The single package under ``src/`` is discovered automatically (the src-layout
convention); pass `--src` to override the source root. Files are created only if
absent — nothing is ever overwritten. Exit code is 0 on success (even if every
file already existed) and 1 on a usage error (no package found, bad name, …).
"""

from __future__ import annotations

import argparse
import json
import keyword
import re
import sys
from pathlib import Path

_MODULE_HEADER = '''\
"""__SUMMARY__"""
'''

_MODULE_FUNC = '''\


def __FUNC__() -> None:
    """TODO: describe what __FUNC__ does."""
'''

_MODULE_CLASS = '''\


class __CLASS__:
    """TODO: describe __CLASS__."""
'''

_TEST_HEADER = '''\
"""Tests for the __IMPORT__ module."""

import __IMPORT__  # noqa: F401
'''

_TEST_FUNC = '''\


def test___FUNC___placeholder():
    """TODO: exercise __FUNC__."""
'''

_TEST_CLASS = '''\


class Test__CLASS__:
    """Tests for __CLASS__."""

    def test_placeholder(self):
        """TODO: exercise __CLASS__."""
'''


class NewModuleError(Exception):
    """A usage error that should be reported and exit non-zero."""


def _fill(template: str, **subs: str) -> str:
    """Replace __TOKEN__ placeholders in a template body."""
    out = template
    for key, value in subs.items():
        out = out.replace(f"__{key}__", value)
    return out


def _valid_identifier(name: str) -> bool:
    """Return whether *name* is a usable Python identifier (not a keyword)."""
    return name.isidentifier() and not keyword.iskeyword(name)


def split_name(name: str) -> list[str]:
    """Split a dotted/slashed module name into its identifier parts.

    Raises NewModuleError if any part is empty or not a valid identifier.
    """
    parts = [p for p in re.split(r"[./]", name) if p != ""]
    if not parts:
        raise NewModuleError(f"invalid module name: {name!r}")
    for part in parts:
        if not _valid_identifier(part):
            raise NewModuleError(f"{part!r} in {name!r} is not a valid Python identifier")
    return parts


def find_package(src: Path) -> Path:
    """Return the single package directory under *src* (the src-layout root).

    A package is a direct child directory of ``src`` (ignoring dunder and
    hidden dirs). Raises NewModuleError when there is not exactly one.
    """
    if not src.is_dir():
        raise NewModuleError(f"source root {src} does not exist")
    packages = [
        d for d in sorted(src.iterdir()) if d.is_dir() and not d.name.startswith((".", "__"))
    ]
    if not packages:
        raise NewModuleError(f"no package directory found under {src}")
    if len(packages) > 1:
        names = ", ".join(p.name for p in packages)
        raise NewModuleError(f"multiple packages under {src} ({names}); pass an explicit --src")
    return packages[0]


def _write_if_absent(path: Path, content: str, created: list[str], skipped: list[str]) -> None:
    """Write *content* to *path* when absent, recording created/skipped paths."""
    if path.exists():
        skipped.append(str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    created.append(str(path))


def _ensure_init_files(pkg: Path, parts: list[str], created: list[str], skipped: list[str]) -> None:
    """Ensure `__init__.py` exists for the package and each intermediate subpackage."""
    node = pkg
    for part in parts[:-1]:
        node = node / part
        _write_if_absent(node / "__init__.py", "", created, skipped)


def render_module(summary: str, funcs: list[str], classes: list[str]) -> str:
    """Render the source-module body: docstring header + stub funcs/classes."""
    body = _fill(_MODULE_HEADER, SUMMARY=summary)
    for cls in classes:
        body += _fill(_MODULE_CLASS, CLASS=cls)
    for func in funcs:
        body += _fill(_MODULE_FUNC, FUNC=func)
    return body


def render_test(import_path: str, funcs: list[str], classes: list[str]) -> str:
    """Render the mirrored test body: import + a TestFoo per class, test per func."""
    body = _fill(_TEST_HEADER, IMPORT=import_path)
    for cls in classes:
        body += _fill(_TEST_CLASS, CLASS=cls)
    for func in funcs:
        body += _fill(_TEST_FUNC, FUNC=func)
    return body


def new_module(
    name: str,
    target: Path,
    *,
    classes: list[str] | None = None,
    src_dir: str = "src",
    tests_dir: str = "tests",
) -> dict[str, list[str]]:
    """Scaffold a source module + mirrored test; return created/skipped paths.

    Raises NewModuleError on a usage problem (no package, bad name, bad class).
    """
    classes = classes or []
    for cls in classes:
        if not _valid_identifier(cls):
            raise NewModuleError(f"{cls!r} is not a valid class name")

    parts = split_name(name)
    stem = parts[-1]
    src_root = target / src_dir
    pkg = find_package(src_root)
    # A module with no class gets one placeholder function so the file is not empty.
    funcs = [] if classes else [stem]

    created: list[str] = []
    skipped: list[str] = []

    module_path = pkg.joinpath(*parts).with_suffix(".py")
    import_path = ".".join([pkg.name, *parts])
    _ensure_init_files(pkg, parts, created, skipped)
    _write_if_absent(
        module_path,
        render_module(f"{stem} module.", funcs, classes),
        created,
        skipped,
    )

    # Mirror the test path the way check_test_layout.py does: relative to the
    # src root (so it includes the package dir), swapping the stem for test_<stem>.
    rel = module_path.relative_to(src_root)
    test_path = (target / tests_dir) / rel.parent / f"test_{stem}.py"
    _write_if_absent(
        test_path,
        render_test(import_path, funcs, classes),
        created,
        skipped,
    )
    return {"created": created, "skipped": skipped}


def _print_report(name: str, report: dict[str, list[str]]) -> None:
    """Print a human-readable created/skipped summary."""
    if report["created"]:
        print(f"Created for '{name}':")
        for path in report["created"]:
            print(f"  + {path}")
    if report["skipped"]:
        print("Skipped (already present):")
        for path in report["skipped"]:
            print(f"  = {path}")
    if not report["created"]:
        print("Nothing to create — every target file already existed.")


def main(argv: list[str] | None = None) -> int:
    """Entry point: scaffold a module + test; return an exit code."""
    parser = argparse.ArgumentParser(
        description="Scaffold a new source module and its mirrored test file.",
    )
    parser.add_argument("name", help="Module name (dotted/slashed for a subpackage).")
    parser.add_argument("target", nargs="?", default=".", help="Repository root (default: .).")
    parser.add_argument(
        "--class",
        dest="classes",
        action="append",
        default=[],
        metavar="CLASS",
        help="Also scaffold a class (and its TestCLASS). Repeatable.",
    )
    parser.add_argument("--src", default="src", help="Source root relative to target.")
    parser.add_argument("--tests", default="tests", help="Tests root relative to target.")
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit a JSON report."
    )
    args = parser.parse_args(argv)

    try:
        report = new_module(
            args.name,
            Path(args.target),
            classes=args.classes,
            src_dir=args.src,
            tests_dir=args.tests,
        )
    except NewModuleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json_output:
        print(json.dumps(report, indent=2))
    else:
        _print_report(args.name, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
