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

With no TARGET it does a second job: it reports which **phase** of the release the
repo is in — A, the bump has yet to land, or B, it landed and only the tag is missing.
That decision used to be prose, comparing `current` against the highest tag, and it
could not be made at all: this script never printed the highest tag in that mode, and
for a repo whose version *is* the tag (Go, Rust, `hatch-vcs`) `current` can never
exceed it, so phase B was unreachable by construction. Both halves are fixed here —
`--changelog` supplies the one piece of committed evidence such a repo does carry.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/check_version_bump.py TARGET --current CURRENT [--target-dir DIR] [--json]
  uv run --python 3.12 --no-project python \
      scripts/check_version_bump.py --current CURRENT [--changelog PATH] [--tag-derived]

Exit codes:
  0  TARGET strictly increases past the floor and is not an existing tag
  1  TARGET does not increase, or that tag already exists
  2  TARGET or CURRENT is not semver-shaped
  3  the phase is ambiguous — the repo's state fits neither A nor B
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_changelog import read_changelog_version  # noqa: E402

_SEMVER = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)

EXIT_OK = 0
EXIT_NOT_INCREASING = 1
EXIT_USAGE = 2
# A phase that cannot be determined is not a version error and not a rejected bump: it
# is "your repo is in a state this flow does not describe", and it gets its own code so
# a caller need not read the reason line to tell it from a backwards version.
EXIT_AMBIGUOUS = 3

PHASE_A = "A"
PHASE_B = "B"
PHASE_AMBIGUOUS = "ambiguous"

# The newest `## [1.7.0]`-style heading in a changelog. `[Unreleased]` is not a version
# and is skipped by the semver shape rather than by name, so `## [Unreleased]` on top of
# a real section does not hide it.


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


def decide_phase(
    current: str,
    highest: str | None,
    pending: str | None,
    tag_derived: bool,
) -> dict[str, Any]:
    """Decide which release phase the repo is in; return phase, target and reason.

    Phase **A** is "the bump has not landed": the version the repo declares is the one
    already tagged, so the run computes a new version and opens the release PR. Phase
    **B** is "it landed and only the tag is missing", and its target is the version the
    committed tree already carries.

    The manifest-declared case, where the bump wrote a version into a file:

    >>> decide_phase("1.6.0", "v1.6.0", None, False)["phase"]
    'A'
    >>> summary = decide_phase("1.7.0", "v1.6.0", None, False)
    >>> summary["phase"], summary["target"]
    ('B', 'v1.7.0')

    The tag-derived case, where `current` is *read from* the highest tag and so can
    never exceed it. Without the changelog the two phases are indistinguishable, which
    is why the evidence is required rather than optional:

    >>> decide_phase("1.6.0", "v1.6.0", "1.7.0", True)["phase"]
    'B'
    >>> decide_phase("1.6.0", "v1.6.0", "1.6.0", True)["phase"]
    'A'
    >>> print(decide_phase("1.6.0", "v1.6.0", None, True)["phase_reason"])
    version is tag-derived, so current can never exceed the highest tag — pass --changelog

    A pending version that disagrees with a declared one leaves two candidate targets
    and no way to choose, so it stops instead of picking:

    >>> decide_phase("1.7.0", "v1.6.0", "1.8.0", False)["phase"]
    'ambiguous'

    A version below its own newest tag means something rewrote history:

    >>> decide_phase("1.5.0", "v1.6.0", None, False)["phase"]
    'ambiguous'

    An untagged repo is on its first release, so it is phase A whatever the declared
    location carries — but a changelog section proves that release already merged:

    >>> decide_phase("0.1.0", None, None, True)["phase"]
    'A'
    >>> decide_phase("0.1.0", None, "0.1.0", False)["phase"]
    'B'
    """
    tag = highest or "none"
    if highest is not None and compare(current, highest) < 0:
        return _phase(
            PHASE_AMBIGUOUS,
            None,
            f"current {current} is below the highest tag {tag} — a reverted bump, or a "
            f"tag cut ahead of the config; neither phase fits",
        )

    landed = _landed_versions(current, highest, pending)
    if len(landed) > 1:
        return _phase(
            PHASE_AMBIGUOUS,
            None,
            f"the declared version and the changelog disagree on what is pending "
            f"({', '.join(sorted(landed))}) — both are above {tag}",
        )
    if landed:
        target = f"v{landed.pop()}"
        return _phase(PHASE_B, target, f"{target} is committed but untagged (highest {tag})")
    if tag_derived and highest is not None and pending is None:
        return _phase(
            PHASE_AMBIGUOUS,
            None,
            "version is tag-derived, so current can never exceed the highest tag "
            "— pass --changelog",
        )
    return _phase(PHASE_A, None, f"the declared version {current} is released as {tag}")


def _landed_versions(current: str, highest: str | None, pending: str | None) -> set[str]:
    """Return the versions that are committed but above every tag — phase B's evidence.

    A set, because the two sources normally agree and one candidate is the whole point;
    two members is the disagreement `decide_phase` refuses to resolve.

    >>> sorted(_landed_versions("1.7.0", "v1.6.0", "1.7.0"))
    ['1.7.0']
    >>> sorted(_landed_versions("1.6.0", "v1.6.0", None))
    []

    On an untagged repo only the changelog counts. The version a manifest carries before
    a first release is a *starting* value that `cargo init` or the skeleton wrote, not a
    landed bump, so treating it as evidence would call every fresh repo phase B:

    >>> sorted(_landed_versions("0.1.0", None, None))
    []
    >>> sorted(_landed_versions("0.1.0", None, "0.1.0"))
    ['0.1.0']
    """
    if highest is None:
        return {pending} if pending is not None else set()
    return {v for v in (current, pending) if v is not None and compare(v, highest) > 0}


def _phase(phase: str, target: str | None, reason: str) -> dict[str, Any]:
    """Package a phase verdict with the exit code that phase implies."""
    return {
        "phase": phase,
        "target": target,
        "phase_reason": reason,
        "exit_code": EXIT_AMBIGUOUS if phase == PHASE_AMBIGUOUS else EXIT_OK,
    }


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


def _suggestions_only(
    current: str,
    target_dir: Path,
    changelog: Path | None = None,
    tag_derived: bool = False,
) -> dict[str, Any]:
    """Build the summary for a run with no target: candidates, and which phase this is.

    `highest_tag` is reported here as well as in a guarded run, and that is the point
    rather than symmetry: the caller's whole phase decision is `current` against the
    highest tag, and this mode used to print `floor` — which is the *max* of the two, so
    identical in both phases and no evidence of either.
    """
    tags = existing_tags(target_dir)
    highest = tags[0] if tags else None
    pending = read_changelog_version(changelog) if changelog is not None else None
    floor = compute_floor(current, tags)
    phase = decide_phase(current, highest, pending, tag_derived)
    return {
        "target": None,
        "current": current,
        "highest_tag": highest,
        "tag_count": len(tags),
        "floor": floor,
        "pending": pending,
        "suggestions": suggest(floor),
        "ok": phase["exit_code"] == EXIT_OK,
        "reason": f"phase {phase['phase']} — {phase['phase_reason']}",
        **phase,
    }


def _print_summary(summary: dict[str, Any]) -> None:
    """Print the human-readable summary, verdict last and on the right stream."""
    print(f"current  {summary['current']}")
    print(f"highest  {summary['highest_tag'] or '(no tags)'}")
    print(f"floor    {summary['floor']}")
    if summary.get("pending") is not None:
        print(f"pending  {summary['pending']}")
    for kind, candidate in summary["suggestions"].items():
        print(f"{kind:<8} {candidate}")
    if "phase" in summary:
        print(f"phase    {summary['phase']}")
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
        "--changelog",
        help=(
            "Changelog to read the pending version from, relative to --target-dir. "
            "Phase detection only; required when the version is tag-derived."
        ),
    )
    parser.add_argument(
        "--tag-derived",
        action="store_true",
        help=(
            "The repo derives its version from the newest tag (Go, Rust, hatch-vcs), so "
            "the declared version is never evidence of a landed bump."
        ),
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    target_dir = Path(args.target_dir).resolve()
    try:
        if args.target is None:
            summary = _suggestions_only(
                args.current,
                target_dir,
                target_dir / args.changelog if args.changelog else None,
                args.tag_derived,
            )
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
