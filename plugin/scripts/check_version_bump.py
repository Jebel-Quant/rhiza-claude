#!/usr/bin/env python3
"""Guard that a release version strictly increases — behind `/rhiza:release`.

`bump-my-version` writes the version wherever the repo declares it, and `git-cliff`
derives the next one from the conventional commits. Neither checks that the result
moves the project **forward**: bump-my-version accepts `0.4.2 -> 0.4.1` without
complaint and has no knowledge of git tags. That gap is what this script closes, and
it matters more than anything else in the release flow — a pushed tag is effectively
permanent, so tagging backwards, or re-tagging an existing version, is the one mistake
that isn't cheaply reversible.

It is deliberately narrow: **read-only, no discovery, no writing.** The current
version is supplied by the caller (from `bump-my-version show current_version`), and
the tags come from git.

Comparison is semver, not string, so `v1.10.0` beats `v1.9.0` where a lexical sort
would not. Pre-releases order per semver §11: `1.0.0-rc1` sorts *below* `1.0.0`.
Build metadata is ignored for ordering, as the spec requires.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/check_version_bump.py TARGET --current CURRENT [--target-dir DIR] [--json]

Exit codes:
  0  TARGET strictly increases past the floor and is not an existing tag
  1  TARGET does not increase, or that tag already exists
  2  TARGET or CURRENT is not semver-shaped
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

_SEMVER = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)

EXIT_OK = 0
EXIT_NOT_INCREASING = 1
EXIT_USAGE = 2


class VersionError(Exception):
    """A version string is not semver-shaped."""


def parse_semver(raw: str) -> tuple[Any, ...]:
    """Parse *raw* into a sortable semver key.

    The prerelease component orders a release **above** its own pre-releases, per
    semver §11, by giving a bare release a higher leading marker than any prerelease.

    >>> parse_semver("v1.2.3") > parse_semver("v1.2.3-rc.1")
    True
    >>> parse_semver("v1.2.3-rc.2") > parse_semver("v1.2.3-rc.10")
    False

    Anything not semver-shaped raises rather than sorting somewhere arbitrary:

    >>> try:
    ...     parse_semver("nightly")
    ... except VersionError as exc:
    ...     print(exc)
    'nightly' is not a semver version (expected vX.Y.Z)
    """
    match = _SEMVER.match(raw.strip())
    if match is None:
        raise VersionError(f"{raw!r} is not a semver version (expected vX.Y.Z)")
    core = (int(match["major"]), int(match["minor"]), int(match["patch"]))
    pre = match["pre"]
    if pre is None:
        return (*core, (1,))
    # Numeric identifiers compare numerically and rank below alphanumeric ones.
    key: list[Any] = [0]
    for part in pre.split("."):
        key.append((0, int(part)) if part.isdigit() else (1, part))
    return (*core, tuple(key))


def compare(left: str, right: str) -> int:
    """Return -1, 0 or 1 comparing two version strings as semver.

    The case a lexical sort gets wrong, which is the whole reason this is not a string
    comparison:

    >>> compare("v1.10.0", "v1.9.0")
    1
    >>> "v1.10.0" > "v1.9.0"
    False

    A pre-release sorts below its own release, and build metadata is ignored for
    ordering:

    >>> compare("1.0.0-rc1", "1.0.0")
    -1
    >>> compare("v2.0.0", "2.0.0+build.5")
    0
    """
    a, b = parse_semver(left), parse_semver(right)
    return (a > b) - (a < b)


def _semver_tags(stdout: str) -> list[str]:
    """Return the semver-shaped tags in git's output, highest first."""
    tags = [t.strip() for t in stdout.splitlines() if t.strip()]
    return sorted((t for t in tags if _SEMVER.match(t)), key=parse_semver, reverse=True)


def existing_tags(target_dir: Path) -> list[str]:
    """Return the repo's semver-shaped ``v*`` tags, highest first."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(  # nosec B603
        [shutil.which("git") or "git", "tag", "--list", "v*"],
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        return []
    return _semver_tags(result.stdout)


def compute_floor(current: str, tags: list[str]) -> str:
    """Return the highest of *current* and *tags* — the version a release must beat.

    The current version alone is not enough: a repo can carry a version lower than its
    newest tag (a reverted bump, a hand-edited manifest), and releasing from that would
    silently reuse a tag.

    >>> compute_floor("0.9.0", ["v1.10.0", "v1.9.0"])
    'v1.10.0'
    >>> compute_floor("1.2.0", [])
    'v1.2.0'
    """
    floor = f"v{current.lstrip('v')}"
    for tag in tags:
        if compare(tag, floor) > 0:
            floor = tag
    return floor


def suggest(floor: str) -> dict[str, str]:
    """Return the candidate next versions above *floor*, keyed by bump kind.

    All of them are offered as a table, and none as a recommendation, because the right
    bump is a judgement no deriver can make. In particular `git-cliff` applies no pre-1.0
    special case: a breaking change at ``0.x`` derives ``v1.0.0``, which spends the
    1.0 signal on a project that may not be ready for it. Showing ``v0.5.0`` beside it
    makes that choice explicit instead of implicit.

    >>> suggest("v0.10.0")
    {'patch': 'v0.10.1', 'minor': 'v0.11.0', 'major': 'v1.0.0'}
    """
    major, minor, patch, *_ = parse_semver(floor)
    return {
        "patch": f"v{major}.{minor}.{patch + 1}",
        "minor": f"v{major}.{minor + 1}.0",
        "major": f"v{major + 1}.0.0",
    }


def check(target_dir: Path, target: str, current: str) -> dict[str, Any]:
    """Evaluate whether *target* is a legal next release; return a summary dict."""
    normalized = f"v{target.lstrip('v')}"
    parse_semver(normalized)
    parse_semver(current)

    tags = existing_tags(target_dir)
    floor = compute_floor(current, tags)
    summary: dict[str, Any] = {
        "target": normalized,
        "current": current,
        "highest_tag": tags[0] if tags else None,
        "tag_count": len(tags),
        "floor": floor,
        "suggestions": suggest(floor),
        "ok": True,
        "reason": f"{normalized} > {floor}",
        "exit_code": EXIT_OK,
    }

    if normalized in tags:
        summary.update(
            ok=False,
            reason=f"tag {normalized} already exists — never move or reuse a tag",
            exit_code=EXIT_NOT_INCREASING,
        )
    elif compare(normalized, floor) <= 0:
        summary.update(
            ok=False,
            reason=(
                f"{normalized} does not strictly increase past {floor} "
                f"(current {current}, highest tag {summary['highest_tag'] or 'none'})"
            ),
            exit_code=EXIT_NOT_INCREASING,
        )
    return summary


def _suggestions_only(current: str, target_dir: Path) -> dict[str, Any]:
    """Build the summary for a run with no target: candidates, and no verdict."""
    floor = compute_floor(current, existing_tags(target_dir))
    return {
        "target": None,
        "current": current,
        "floor": floor,
        "suggestions": suggest(floor),
        "ok": True,
        "reason": "no target given — listing suggestions only",
        "exit_code": EXIT_OK,
    }


def _print_summary(summary: dict[str, Any]) -> None:
    """Print the human-readable summary, verdict last and on the right stream."""
    print(f"current  {summary['current']}")
    if summary["target"] is not None:
        print(f"highest  {summary['highest_tag'] or '(no tags)'}")
    print(f"floor    {summary['floor']}")
    for kind, candidate in summary["suggestions"].items():
        print(f"{kind:<8} {candidate}")
    if summary["target"] is not None:
        print(f"target   {summary['target']}")
    sys.stdout.flush()
    label, stream = ("ok", sys.stdout) if summary["ok"] else ("error", sys.stderr)
    print(f"{label}       {summary['reason']}", file=stream)


def main(argv: list[str] | None = None) -> int:
    """Entry point: guard the proposed release version and return an exit code."""
    parser = argparse.ArgumentParser(
        description="Guard that a release version strictly increases past every prior release.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="Proposed release version (e.g. v1.2.0). Omit to only list suggestions.",
    )
    parser.add_argument(
        "--current",
        required=True,
        help="The version the repo states now (from `bump-my-version show current_version`).",
    )
    parser.add_argument("--target-dir", default=".", help="Repository root (default: cwd).")
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    target_dir = Path(args.target_dir).resolve()
    try:
        if args.target is None:
            summary = _suggestions_only(args.current, target_dir)
        else:
            summary = check(target_dir, args.target, args.current)
    except VersionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        _print_summary(summary)
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
