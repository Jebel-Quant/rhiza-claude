#!/usr/bin/env python3
"""The docstring half of `check_doc_examples.py`: the doctests under a source root.

`interrogate` answers "is there a docstring?". Nothing answered "does the example inside
it still evaluate to what it claims?" — and a docstring that lies is worse than one that
is missing, because it reads as verified. The rhiza template closes this in a managed repo
with `.rhiza/tests/test_docstrings.py`; this module is that check without the `.rhiza/`
directory.

Two passes, and the split is what lets the first one work anywhere:

* **Inventory** — `ast` reads every docstring and `doctest.DocTestParser` finds the
  examples. No import, so no dependency has to be installed, and a malformed example
  (inconsistent leading whitespace, a `>>>` with no output) is already a violation. It
  also reports *how many* examples exist, which is the number separating "12 examples, all
  passing" from the far more common "0 examples" — a silence that reads as a pass.
* **Execution** (opt-in) — each module is imported and handed to `doctest.testmod`, with
  the template's own option flags so a `...` means the same thing in both places.

A module that cannot be imported is reported as **unmeasured**, never failed: a missing
third-party dependency in the ambient interpreter is a fact about the environment, not a
defect in the docstring.
"""

from __future__ import annotations

import ast
import contextlib
import doctest
import importlib
import io
import sys
from pathlib import Path
from typing import Any

# Directories that are never a repo's own source: virtualenvs, build output, vendored
# code — plus `tests`, whose examples are not documentation and whose modules a scoring
# run should not import. A source root of `.` (what `language_profile.py` reports for a
# manifest-less repo) makes all of these reachable, which is why the list exists.
_SKIP_DIRS = frozenset(
    {".git", ".venv", "venv", ".tox", "__pycache__", "build", "dist", "node_modules", "tests"}
)

# What the template's own doctest runner uses, so an example that passes there passes here.
_OPTIONFLAGS = doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE

_DOCUMENTABLE = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _node_name(node: ast.AST) -> str:
    """Return a readable name for the docstring's owner."""
    return getattr(node, "name", "<module>")


def _node_line(node: ast.AST) -> int:
    """Return the line the docstring's owner starts on (1 for a module)."""
    return getattr(node, "lineno", 1)


def source_files(root: Path) -> list[Path]:
    """Return the repo's own `.py` files under *root*, skipping vendored and test trees."""
    return sorted(p for p in root.rglob("*.py") if not (set(p.parts) & _SKIP_DIRS))


def docstring_examples(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (example locations, problems) for every docstring in *path*.

    No import happens here, so this pass works in an environment where the module's
    dependencies are absent — and a docstring whose example is malformed is a violation
    before anything is run.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
        return [], [f"{path}: does not parse — {exc}"]

    parser = doctest.DocTestParser()
    found: list[dict[str, Any]] = []
    problems: list[str] = []
    for node in ast.walk(tree):
        text = ast.get_docstring(node, clean=False) if isinstance(node, _DOCUMENTABLE) else None
        if not text:
            continue
        try:
            examples = parser.get_examples(text)
        except ValueError as exc:
            problems.append(f"{path}:{_node_line(node)}: malformed doctest — {exc}")
            continue
        if examples:
            found.append(
                {
                    "file": str(path),
                    "object": _node_name(node),
                    "line": _node_line(node),
                    "examples": len(examples),
                }
            )
    return found, problems


def run_doctests(root: Path, paths: list[Path]) -> dict[str, Any]:
    """Import each module under *root*, run its doctests, and summarise the result.

    An unimportable module is unmeasured rather than failed (see the module docstring).
    The count comes back so the caller can say so, instead of a partial run reading as a
    complete one.
    """
    attempted = failed = 0
    failures: list[str] = []
    unimportable: list[str] = []
    # Resolved only here: the reports quote *root* as it was given, so a relative
    # `--target-dir` keeps the paths short, while an import path has to be absolute or it
    # would follow the process's cwd.
    import_path = str(root.resolve())
    sys.path.insert(0, import_path)
    try:
        for path in paths:
            name = ".".join(path.relative_to(root).with_suffix("").parts).removesuffix(".__init__")
            try:
                module = importlib.import_module(name)
            except Exception as exc:  # noqa: BLE001 - any module-level failure is "unmeasured"
                unimportable.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                result = doctest.testmod(module, verbose=False, optionflags=_OPTIONFLAGS)
            attempted += result.attempted
            failed += result.failed
            if result.failed:
                failures.append(
                    f"{name}: {result.failed}/{result.attempted} example(s) failed\n"
                    f"{buffer.getvalue().strip()}"
                )
    finally:
        sys.path.remove(import_path)
    return {
        "attempted": attempted,
        "failed": failed,
        "failures": failures,
        "unimportable": unimportable,
    }


def _notes(total: int, execution: dict[str, Any] | None) -> list[str]:
    """Build the notes for this half — the silences that would otherwise read as passes."""
    if not total:
        return [
            "no doctest examples found — docstring coverage says nothing about whether the "
            "docstrings are true, and here there is nothing to check"
        ]
    if execution is None:
        return [f"{total} example(s) found but not run — pass --run to execute them"]
    if execution["unimportable"]:
        return [
            f"{len(execution['unimportable'])} module(s) could not be imported, so their "
            "examples are unmeasured, not passing — run this inside the project's own "
            "environment to measure them"
        ]
    return []


def docstring_report(root: Path, *, run: bool) -> dict[str, Any]:
    """Inventory (and optionally run) every doctest example under *root*."""
    if not root.is_dir():
        return {
            "source_root": str(root),
            "present": False,
            "examples": 0,
            "locations": [],
            "violations": [],
            "notes": [f"no source root at {root} — docstring examples are out of scope"],
        }

    paths = source_files(root)
    locations: list[dict[str, Any]] = []
    violations: list[str] = []
    for path in paths:
        found, problems = docstring_examples(path)
        locations.extend(found)
        violations.extend(problems)
    total = sum(int(item["examples"]) for item in locations)

    execution: dict[str, Any] | None = None
    if run and total:
        execution = run_doctests(root, paths)
        violations.extend(execution["failures"])

    report: dict[str, Any] = {
        "source_root": str(root),
        "present": True,
        "files": len(paths),
        "examples": total,
        "locations": locations,
        "violations": violations,
        "notes": _notes(total, execution),
    }
    if execution is not None:
        report["execution"] = execution
    return report


def print_report(docs: dict[str, Any]) -> None:
    """Print the docstring half of a report as text."""
    if not docs["present"]:
        print(f"{'unavailable':<12} docstring examples ({docs['source_root']} is not a directory)")
        return
    print(
        f"{'docstrings':<12} {docs['source_root']}: {docs['files']} file(s), "
        f"{docs['examples']} example(s) in {len(docs['locations'])} docstring(s)"
    )
    for item in docs["locations"]:
        print(
            f"{'example':<12} {item['file']}:{item['line']} {item['object']} ({item['examples']})"
        )
    execution = docs.get("execution")
    if execution is not None:
        print(
            f"{'ran':<12} {execution['attempted']} example(s), {execution['failed']} failed, "
            f"{len(execution['unimportable'])} module(s) unimportable"
        )
