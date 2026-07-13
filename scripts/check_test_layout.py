#!/usr/bin/env python3
"""Check that the test layout mirrors the source layout.

Enforces a strict test/source parity so tests are easy to locate and no test
drifts loose from what it covers:

  * every source module ``<src>/…/xyz.py`` has a test file
    ``<tests>/…/test_xyz.py`` (nested packages are mirrored);
  * every top-level ``class A`` in a source module has a matching ``TestA``
    class in that test file;
  * no test file lacks a corresponding source module (no orphan test files);
  * no ``Test*`` class lacks a corresponding source class (no orphan test
    classes).

``__init__.py`` and ``conftest.py`` are ignored on both sides. Test *functions*
are unconstrained — the rules bind files and classes only.

Usage:
  python3 scripts/check_test_layout.py [--src DIR] [--tests DIR]

Exits 0 when the layout is clean, 1 (listing every violation) otherwise.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

_IGNORED = {"__init__.py", "conftest.py"}


def _top_level_classes(path: Path) -> set[str]:
    """Return the names of top-level classes defined in *path*."""
    tree = ast.parse(path.read_text(), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _source_modules(src: Path) -> list[Path]:
    """Return the source ``.py`` modules under *src* (ignoring dunder/conftest)."""
    return sorted(p for p in src.rglob("*.py") if p.name not in _IGNORED)


def _test_files(tests: Path) -> list[Path]:
    """Return the ``test_*.py`` files under *tests* (ignoring conftest)."""
    return sorted(p for p in tests.rglob("test_*.py") if p.name not in _IGNORED)


def check(src: Path, tests: Path) -> list[str]:
    """Return a list of layout violations (empty when the layout is clean)."""
    errors: list[str] = []

    # Forward: every source module needs a mirrored test file + Test* classes.
    for module in _source_modules(src):
        rel = module.relative_to(src)
        test_path = tests / rel.parent / f"test_{module.stem}.py"
        if not test_path.exists():
            errors.append(f"missing test file {test_path} for source module {module}")
            continue
        test_classes = _top_level_classes(test_path)
        for cls in sorted(_top_level_classes(module)):
            if f"Test{cls}" not in test_classes:
                errors.append(f"missing class Test{cls} in {test_path} for class {cls} in {module}")

    # Reverse: every test file/class must trace back to a source module/class.
    for test_file in _test_files(tests):
        rel = test_file.relative_to(tests)
        source_name = test_file.stem[len("test_") :]
        source_path = src / rel.parent / f"{source_name}.py"
        if not source_path.exists():
            errors.append(f"orphan test file {test_file} (no source module {source_path})")
            continue
        source_classes = _top_level_classes(source_path)
        for cls in sorted(_top_level_classes(test_file)):
            if cls.startswith("Test") and cls[len("Test") :] not in source_classes:
                errors.append(
                    f"orphan test class {cls} in {test_file} "
                    f"(no class {cls[len('Test') :]} in {source_path})"
                )

    return errors


def main(argv: list[str] | None = None) -> int:
    """Entry point: check the layout and return an exit code."""
    parser = argparse.ArgumentParser(description="Check test/source layout parity.")
    parser.add_argument("--src", default="src", help="Source directory (default: src).")
    parser.add_argument("--tests", default="tests", help="Tests directory (default: tests).")
    args = parser.parse_args(argv)

    errors = check(Path(args.src), Path(args.tests))
    if errors:
        print("Test-layout check failed:", file=sys.stderr)
        for err in errors:
            print(f"  ✗ {err}", file=sys.stderr)
        return 1
    print("Test layout OK: tests mirror sources 1:1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
