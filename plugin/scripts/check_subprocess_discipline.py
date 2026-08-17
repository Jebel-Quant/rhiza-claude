#!/usr/bin/env python3
"""Require every `subprocess` call to notice when the process failed.

Ruff's `S` rules police *how* a process is launched. They say nothing about the failure
mode that actually matters in this plugin: launching git correctly and then ignoring that
it exited non-zero. Ten of the sixteen call sites here pass ``check=False`` and read the
returncode by hand — correct at every site today, but nothing made it stay that way, so a
new call site could swallow a failed sync and the build would stay green.

Three rules, checked with `ast` over `plugin/scripts/`:

1. **``check=`` must be passed explicitly.** ``subprocess.run`` defaults to
   ``check=False``, so omitting it means "ignore failures" without ever saying so. Whether
   a failure should raise is exactly the decision this checker wants written down.

2. **A ``check=False`` call must account for the returncode**, by one of:
   *inspecting* it (``result.returncode`` somewhere in the enclosing function), *handing
   the process back* (the function returns a ``CompletedProcess``, so the caller decides),
   or *declaring the exception* with an ``rc-ignored:`` comment on the call.

3. **An ``rc-ignored:`` comment needs a reason** after the colon. A bare marker is a way
   to silence the checker without thinking, which is what it exists to prevent.

Rule 2's third arm is not a loophole — some calls genuinely should ignore the code.
``git config --get user.name`` exits 1 when the key is simply unset, and the empty stdout
*is* the answer; raising or branching there would invent a failure. The point is that such
a case is now stated at the call site instead of being indistinguishable from an oversight.

Usage:
  uv run --python 3.12 --no-project python \
    plugin/scripts/check_subprocess_discipline.py [--root DIR]

Exits 0 when every call site is disciplined, 1 (listing each violation) otherwise.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_layout import SCRIPTS_DIR  # noqa: E402

# The `subprocess` entry points that launch a process and hand back its result. `Popen` is
# absent on purpose: it has no `check` argument and nothing here uses it.
_LAUNCHERS = frozenset({"run", "call", "check_call", "check_output"})

# `check_call` and `check_output` raise on a non-zero exit by definition, so `check=` is
# neither accepted nor needed there.
_ALWAYS_CHECKS = frozenset({"check_call", "check_output"})

_MARKER = "rc-ignored:"


def _is_subprocess_launch(node: ast.Call) -> str | None:
    """Return the `subprocess` function *node* calls, or None when it calls something else."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _LAUNCHERS:
        return None
    if isinstance(func.value, ast.Name) and func.value.id == "subprocess":
        return func.attr
    return None


def _check_keyword(node: ast.Call) -> ast.keyword | None:
    """Return the ``check=`` keyword passed to *node*, or None when it was omitted."""
    return next((kw for kw in node.keywords if kw.arg == "check"), None)


def _is_false(value: ast.expr) -> bool:
    """Is *value* the literal ``False``?"""
    return isinstance(value, ast.Constant) and value.value is False


def _inspects_returncode(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Does *func* read ``.returncode`` anywhere in its body?"""
    return any(
        isinstance(node, ast.Attribute) and node.attr == "returncode" for node in ast.walk(func)
    )


def _returns_completed_process(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Does *func* annotate its return type as a ``CompletedProcess``?

    The "hand it back" arm: a function whose contract is to return the process has
    delegated the returncode decision to its caller, which this checker then holds to the
    same three rules.
    """
    if func.returns is None:
        return False
    return "CompletedProcess" in ast.unparse(func.returns)


def _marker_reason(lines: list[str], node: ast.Call) -> str | None:
    """Return the text after ``rc-ignored:`` on or just above *node*, or None.

    The span starts one line **above** the call, because that is where the comment
    naturally goes: a multi-line `subprocess.run(...)` often has no room for a trailing
    comment, and the argument list is the wrong place to explain the exit code anyway.

    An empty string means the marker is present but unexplained, which rule 3 rejects;
    None means there is no marker at all.
    """
    start = max(0, node.lineno - 2)
    for line in lines[start : (node.end_lineno or node.lineno)]:
        if _MARKER in line:
            return line.split(_MARKER, 1)[1].strip()
    return None


def _enclosing_function(
    tree: ast.Module, node: ast.Call
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return the innermost function containing *node*, or None at module level.

    Innermost matters: `_skeleton_common.git_identity` wraps its call in a nested `read`
    helper, and it is `read` whose handling of the returncode is the question. Of the
    functions containing the call, the innermost is the one declared last.
    """
    containing = [
        candidate
        for candidate in ast.walk(tree)
        if isinstance(candidate, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(inner is node for inner in ast.walk(candidate))
    ]
    return max(containing, key=lambda func: func.lineno) if containing else None


def _unchecked_violations(
    tree: ast.Module, lines: list[str], node: ast.Call, name: str, where: str
) -> list[str]:
    """Return the violations for a call that passes `check=False`.

    Split out of `_violations_for_call` so each half answers one question: that one asks
    whether `check=` is present and false, this one asks whether being false is
    *justified* — by an explanatory marker, or by the enclosing function accounting for
    the returncode itself.
    """
    reason = _marker_reason(lines, node)
    if reason is not None:
        if reason:
            return []
        return [
            f"{where}: `{_MARKER}` needs a reason after the colon, naming which "
            "returncodes are expected and why ignoring them is right here."
        ]

    func = _enclosing_function(tree, node)
    if func is not None and (_inspects_returncode(func) or _returns_completed_process(func)):
        return []
    return [
        f"{where}: subprocess.{name}(..., check=False) never accounts for the returncode. "
        "Inspect `.returncode`, return the CompletedProcess so the caller can, or add a "
        f"`# {_MARKER} <reason>` comment on the call."
    ]


def _violations_for_call(
    tree: ast.Module, lines: list[str], node: ast.Call, name: str, where: str
) -> list[str]:
    """Return the rule violations for one `subprocess` call."""
    keyword = _check_keyword(node)
    if name in _ALWAYS_CHECKS:
        return []  # raises by definition; `check=` does not apply
    if keyword is None:
        return [
            f"{where}: subprocess.{name}(...) omits `check=`. Pass it explicitly — the "
            "default is check=False, which ignores failures without saying so."
        ]
    if not _is_false(keyword.value):
        return []
    return _unchecked_violations(tree, lines, node, name, where)


def check_module(path: Path, root: Path) -> list[str]:
    """Return the discipline violations in one module."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text, filename=str(path))
    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else path

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _is_subprocess_launch(node)
        if name is None:
            continue
        where = f"{rel}:{node.lineno}"
        violations.extend(_violations_for_call(tree, lines, node, name, where))
    return violations


def check(root: Path) -> list[str]:
    """Return every discipline violation in *root*'s bundled scripts, in file order.

    *root* is the **repository** root; the scripts directory is derived from
    `_rhiza_layout` rather than hardcoded, like every other checker that spans both
    halves of the repo.
    """
    scripts = root / SCRIPTS_DIR
    found: list[str] = []
    for module in sorted(scripts.rglob("*.py")):
        found.extend(check_module(module, root))
    return found


def main(argv: list[str] | None = None) -> int:
    """Entry point: check subprocess discipline and return an exit code."""
    parser = argparse.ArgumentParser(
        description="Require every subprocess call to account for a non-zero exit.",
    )
    parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    args = parser.parse_args(argv)

    violations = check(Path(args.root).resolve())

    for violation in violations:
        print(violation, file=sys.stderr)
    if violations:
        print(
            f"\n{len(violations)} subprocess call(s) do not account for failure. "
            "See plugin/scripts/check_subprocess_discipline.py for the three rules.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
