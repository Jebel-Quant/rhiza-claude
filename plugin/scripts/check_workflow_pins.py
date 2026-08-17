#!/usr/bin/env python3
"""Assert the workflows agree about the versions they pin.

A SHA pin is two halves: the SHA, which binds, and the `# v10.0.0` comment, which is the
only half a human reading the diff can act on. Nothing checked that the halves agreed, and
they stopped agreeing — one `setup-uv` call site kept a `# v7.1.1` comment through a bump
to v10.0.0, so an auditor asking "which release is this" got two answers from one SHA.

The uv *version input* is the same failure one level down, and it matters more. Everything
this repo pins flows through uv — `UV_CONSTRAINT` and `UV_PYTHON` are exported for it to
consume, so 14 pinned tools resolve however uv decides to resolve them. That input is
duplicated at every call site, and `auto-tag.yml` simply did not have it: the job that
decides whether a release tag is created floated its uv. Dependabot watches the action pin
above the input and cannot see the input, so nothing would have said so.

Three rules, over `.github/workflows/*.yml` and any composite action beside them:

1. every remote ``uses:`` is pinned to a full 40-character SHA and annotated with a
   ``# <version>`` comment;
2. all call sites of one action repository agree — same SHA, same comment. Sub-path uses
   (``actions/cache/save``) are the same repository as their parent and are held to it;
3. every ``astral-sh/setup-uv`` step passes a ``version:`` input, and all of them agree.

Rule 3 is the narrow, tool-specific one, and it is deliberately not generalised to "every
action input agrees": `python-version` legitimately differs per job, and a rule that
guessed which inputs were pins would either miss this one or forbid that.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/check_workflow_pins.py [--workflows .github/workflows]

Exit codes:
  0  every pin agrees
  1  a pin is unpinned, unannotated, or disagrees with another call site
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WORKFLOWS_DIR = ".github/workflows"
"""Default root to scan, relative to the repository root."""

UV_ACTION = "astral-sh/setup-uv"
"""The one action whose version *input* is checked, not just its own pin."""

# `uses: owner/repo[/subpath]@<sha> # comment`, matched one line at a time. The comment
# group is optional so an unannotated pin is reported by rule 1 rather than skipped as
# "not a pin", and `indent` counts the whitespace before an optional `- ` because the rest
# of the step is indented relative to it. A local action (`uses: ./x`) has no `owner/repo`
# and so never matches — nothing SHA-pins it, and nothing here should ask it to.
_USES = re.compile(
    r"^(?P<indent>\s*)-?\s*uses:\s*"
    r"(?P<action>[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+)@(?P<ref>\S+)"
    r"(?:\s*#\s*(?P<comment>\S+))?\s*$"
)
_SHA = re.compile(r"^[0-9a-f]{40}$")
_VERSION_INPUT = re.compile(r"^\s*version:\s*['\"]?(?P<value>[^'\"\s#]+)")


class Pin:
    """One ``uses:`` line: which action, at which SHA, annotated with which version.

    *where* is the ``file:line`` the violation messages quote, and *version_input* is the
    ``version:`` value from the step's ``with:`` block — ``None`` when the step has none,
    which is what rule 3 reports for :data:`UV_ACTION`.
    """

    def __init__(self, action: str, ref: str, comment: str | None, where: str) -> None:
        """Record one pin and the step input that came with it."""
        self.action = action
        self.ref = ref
        self.comment = comment
        self.where = where
        self.version_input: str | None = None

    @property
    def repository(self) -> str:
        """The action *repository*, dropping any sub-path.

        Sub-path actions ship from their parent's tree, so they share its SHA and must
        share its annotation — grouping by the full ``uses:`` value would let
        ``actions/cache`` and ``actions/cache/save`` drift apart unnoticed.

        >>> Pin("actions/cache/save", "abc", "v6.1.0", "ci.yml:1").repository
        'actions/cache'
        >>> Pin("astral-sh/setup-uv", "abc", "v10.0.0", "ci.yml:1").repository
        'astral-sh/setup-uv'
        """
        owner, _, rest = self.action.partition("/")
        return f"{owner}/{rest.split('/')[0]}"


def _step_version_input(lines: list[str], start: int, indent: int) -> str | None:
    """Return the ``version:`` input of the step whose ``uses:`` line is at *start*.

    Reads forward to the end of that step. ``with:`` is a sibling key of ``uses:`` rather
    than a child, so the block continues at the *same* indentation and ends where a new
    list item begins or the indentation drops — not, as a first cut had it, at the first
    line no deeper than ``uses:``, which found the pin in none of six real call sites.
    Comment and blank lines are skipped rather than ending the step; a ``with:`` block
    introduced by a comment is the usual shape here.
    """
    for line in lines[start + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip()) < indent or line.lstrip().startswith("- "):
            return None
        match = _VERSION_INPUT.match(line)
        if match:
            return match.group("value")
    return None


def collect_pins(path: Path, rel: str) -> list[Pin]:
    """Return every action pin declared in the workflow at *path*."""
    lines = path.read_text(encoding="utf-8").splitlines()
    pins: list[Pin] = []
    for index, line in enumerate(lines):
        match = _USES.match(line)
        if match is None:
            continue
        pin = Pin(
            match.group("action"),
            match.group("ref"),
            match.group("comment"),
            f"{rel}:{index + 1}",
        )
        pin.version_input = _step_version_input(lines, index, len(match.group("indent")))
        pins.append(pin)
    return pins


def _unpinned_violations(pins: list[Pin]) -> list[str]:
    """Rule 1: every pin is a full SHA carrying a version comment."""
    violations: list[str] = []
    for pin in pins:
        if not _SHA.match(pin.ref):
            violations.append(f"{pin.where}: {pin.action} is pinned to {pin.ref!r}, not a SHA")
        elif pin.comment is None:
            violations.append(
                f"{pin.where}: {pin.action} has no '# <version>' comment — the SHA is the "
                "half that binds, the comment is the half a reviewer can read"
            )
    return violations


def _disagreement(label: str, values: dict[str, str]) -> list[str]:
    """Report *values* (call site -> value) when they do not all agree on one *label*."""
    if len(set(values.values())) <= 1:
        return []
    sites = ", ".join(f"{where}={value!r}" for where, value in sorted(values.items()))
    return [f"{label} disagrees across call sites: {sites}"]


def _parity_violations(pins: list[Pin]) -> list[str]:
    """Rule 2: all call sites of one action repository share a SHA and a comment."""
    violations: list[str] = []
    repositories = sorted({pin.repository for pin in pins})
    for repository in repositories:
        sites = [pin for pin in pins if pin.repository == repository]
        violations += _disagreement(f"{repository} SHA", {p.where: p.ref for p in sites})
        violations += _disagreement(
            f"{repository} version comment",
            {p.where: p.comment for p in sites if p.comment is not None},
        )
    return violations


def _uv_input_violations(pins: list[Pin]) -> list[str]:
    """Rule 3: every :data:`UV_ACTION` step pins uv, and all of them pin the same uv."""
    sites = [pin for pin in pins if pin.repository == UV_ACTION]
    violations = [
        f"{pin.where}: {UV_ACTION} passes no 'version:' input, so this job resolves "
        "whatever uv release is current at run time"
        for pin in sites
        if pin.version_input is None
    ]
    pinned = {p.where: p.version_input for p in sites if p.version_input is not None}
    return violations + _disagreement("uv version input", pinned)


def check_workflows(root: Path) -> list[str]:
    """Return every pin violation under the workflows directory *root*.

    Composite actions beside the workflows are read too: moving a pin into one is a
    reasonable way to de-duplicate it, and it must not be a way to leave the gate.
    """
    pins: list[Pin] = []
    for path in sorted(root.rglob("*.yml")) + sorted(root.rglob("*.yaml")):
        # `as_posix`, not `str`: the relative path goes into the violation messages, and on
        # Windows `str` spells it `shared\action.yaml` — a workflow path with a separator no
        # workflow file uses. A direct child comes back as its bare name either way.
        pins += collect_pins(path, path.relative_to(root).as_posix())
    return _unpinned_violations(pins) + _parity_violations(pins) + _uv_input_violations(pins)


def main(argv: list[str] | None = None) -> int:
    """Entry point: report disagreeing pins and return an exit code."""
    parser = argparse.ArgumentParser(
        description="Assert the workflows agree about the versions they pin.",
    )
    parser.add_argument(
        "--workflows",
        default=WORKFLOWS_DIR,
        help=f"Directory of workflow files to check (default: {WORKFLOWS_DIR}).",
    )
    args = parser.parse_args(argv)

    root = Path(args.workflows)
    if not root.is_dir():
        print(f"No workflows directory at {root}", file=sys.stderr)
        return 1

    violations = check_workflows(root)
    for violation in violations:
        print(violation, file=sys.stderr)
    if violations:
        print(f"{len(violations)} pin problem(s)", file=sys.stderr)
        return 1
    print("workflow pins agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
