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

``__init__.py`` and ``conftest.py`` are ignored on both sides, and the
``tests/benchmarks/`` and ``tests/stress/`` trees are exempt entirely — those
hold benchmarks and stress tests that need not mirror a source module. Test
*functions* are unconstrained — the rules bind files and classes only.

Repositories that deliberately organise tests by *behaviour* rather than 1:1
mirroring (and guarantee per-module coverage another way, e.g. a 100% coverage
gate) can opt out via a ``[tool.check_test_layout]`` table in ``pyproject.toml``::

    [tool.check_test_layout]
    enforce = false
    reason = "Tests are grouped by behaviour; coverage is enforced by pytest."

``enforce = false`` requires a non-empty ``reason`` so the deviation is always
documented. The same table accepts ``exempt_dirs = [...]`` to extend the
built-in benchmarks/stress exemptions when parity *is* enforced.

Usage:
  uv run --python 3.12 --no-project python \
    scripts/check_test_layout.py [--src DIR] [--tests DIR] [--config FILE]

Exits 0 when the layout is clean (or parity is intentionally not enforced),
1 (listing every violation) otherwise.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Mapping
from pathlib import Path

try:  # py3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - older interpreters
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None  # type: ignore

_IGNORED = {"__init__.py", "conftest.py"}

# Top-level directories under the tests root that are exempt from parity by
# default: they hold benchmarks / stress tests that need not mirror a source
# module. A repo can extend this set via ``[tool.check_test_layout] exempt_dirs``.
_DEFAULT_EXEMPT_DIRS = {"benchmarks", "stress"}


def _coerce_scalar(raw: str) -> object:
    """Coerce a TOML scalar/array literal to a Python value (fallback reader).

    Handles the narrow subset the ``[tool.check_test_layout]`` table uses:
    quoted strings, ``true``/``false`` booleans, and single-line arrays of
    quoted strings. Everything else is returned as its stripped token.
    """
    raw = raw.strip()
    if raw[:1] in {'"', "'"}:
        end = raw.find(raw[0], 1)
        return raw[1:end] if end != -1 else raw[1:]
    if raw.startswith("["):
        end = raw.find("]")
        inner = raw[1 : end if end != -1 else len(raw)]
        return [v for v in (_coerce_scalar(item) for item in inner.split(",")) if v != ""]
    token = raw.split("#", 1)[0].strip()
    if token == "true":
        return True
    if token == "false":
        return False
    return token


def _parse_flat_section(text: str, header: str) -> dict[str, object]:
    """Extract a single flat ``[header]`` table from TOML *text*.

    A dependency-free fallback for interpreters without ``tomllib``/``tomli``
    (the plugin runs under the ambient ``python3``, which may predate 3.11).
    It recognises only the flat ``key = value`` table this checker reads.
    """
    want = f"[{header}]"
    out: dict[str, object] = {}
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("["):
            in_section = stripped == want
            continue
        if not in_section or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = _coerce_scalar(value)
    return out


def _read_config(pyproject: Path) -> dict[str, object]:
    """Return the ``[tool.check_test_layout]`` table from *pyproject* (empty if absent).

    Prefers ``tomllib``/``tomli`` when importable; otherwise uses the flat-table
    fallback so the opt-out is honoured regardless of interpreter version.
    """
    if not pyproject.is_file():
        return {}
    text = pyproject.read_text(encoding="utf-8")
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except ValueError:
            return {}
        section = data.get("tool", {}).get("check_test_layout", {})
        return section if isinstance(section, dict) else {}
    return _parse_flat_section(text, "tool.check_test_layout")


def _exempt_dirs(config: Mapping[str, object]) -> set[str]:
    """Return the exempt top-level test dirs: defaults plus any from *config*."""
    dirs = set(_DEFAULT_EXEMPT_DIRS)
    extra = config.get("exempt_dirs")
    if isinstance(extra, list):
        dirs |= {str(d) for d in extra}
    return dirs


def _top_level_classes(path: Path) -> set[str]:
    """Return the names of top-level classes defined in *path*."""
    tree = ast.parse(path.read_text(), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _source_modules(src: Path) -> list[Path]:
    """Return the source ``.py`` modules under *src* (ignoring dunder/conftest)."""
    return sorted(p for p in src.rglob("*.py") if p.name not in _IGNORED)


def _test_files(tests: Path, exempt: set[str] | None = None) -> list[Path]:
    """Return the ``test_*.py`` files under *tests* (ignoring conftest/exempt dirs)."""
    exempt = _DEFAULT_EXEMPT_DIRS if exempt is None else exempt
    return sorted(
        p
        for p in tests.rglob("test_*.py")
        if p.name not in _IGNORED and p.relative_to(tests).parts[0] not in exempt
    )


def check(src: Path, tests: Path, config: Mapping[str, object] | None = None) -> list[str]:
    """Return a list of layout violations (empty when the layout is clean)."""
    exempt = _exempt_dirs(config or {})
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
    for test_file in _test_files(tests, exempt):
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
    parser.add_argument(
        "--config",
        default="pyproject.toml",
        help="pyproject.toml providing [tool.check_test_layout] (default: pyproject.toml).",
    )
    args = parser.parse_args(argv)

    config = _read_config(Path(args.config))

    if not config.get("enforce", True):
        reason = str(config.get("reason", "")).strip()
        if not reason:
            print(
                "Test-layout check misconfigured: [tool.check_test_layout] enforce=false "
                "requires a non-empty 'reason' documenting the intentional layout.",
                file=sys.stderr,
            )
            return 1
        print(f"Test layout OK: parity not enforced by request — {reason}")
        return 0

    errors = check(Path(args.src), Path(args.tests), config)
    if errors:
        print("Test-layout check failed:", file=sys.stderr)
        for err in errors:
            print(f"  ✗ {err}", file=sys.stderr)
        return 1
    print("Test layout OK: tests mirror sources 1:1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
