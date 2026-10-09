#!/usr/bin/env python3
"""List open pull/merge requests with the facts a merge order is decided from.

`/rhiza:history` reads a backlog as a whole: which requests are obsolete, which order
the rest should merge in, what to pick up next. ``pr_status.py`` already answers *is it
green*, and ``issue_status.py`` already answers *can this issue be fixed without a
judgement call*. Neither knows what a request **touches**, and that is what decides an
order: two requests editing the same file conflict on whichever merges second, so the
one that rebases should be the one that is cheaper to rebase.

This script gathers facts and stops. Per request: its branches, draft state, author,
age and idle time, whether the forge says it merges cleanly, the files it changes, and
the issues it closes — with the ones already closed called out, since a request whose
only purpose was fixing an issue someone else already fixed is the commonest kind of
obsolete. Across requests: every pair that changes a file in common. **Which order to
merge in is not here** — it weighs risk, size and intent, and that judgement belongs in
the command's prose.

The two forges disagree about how much of this a listing carries:

    gh   pr list --json …,files,mergeable,closingIssuesReferences
         -> everything, in one call
    glab mr list --output json
         -> no files and no closing references; `has_conflicts` instead of `mergeable`

On GitLab the files come from ``glab mr diff <iid> --raw``, one call per request, read
off the ``diff --git a/X b/Y`` headers — git's own format, not a payload shape that could
drift. The closing references come from GitLab's closing keywords in the description,
which is how GitLab itself decides them; ``closes_source`` says which of the two each
request's list came from, so a caller knows how far to trust an empty one.

Usage:
  uv run --python 3.12 --no-project python \\
      scripts/pr_inventory.py [--target-dir DIR] [--limit N] [--json] [--dry-run]

Exit codes:
  0  report printed
  1  the platform CLI is missing, failed, or answered something unreadable
  2  the platform could not be determined
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import shutil
import subprocess  # nosec B404
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_forge import PlatformError, detect_platform  # noqa: E402

EXIT_OK = 0
EXIT_CLI_FAILED = 1
EXIT_NO_PLATFORM = 2

# Spelled out rather than globbed: gh errors on an unknown field, so this list is itself
# a contract with the CLI. Each one was checked against `gh pr list` on this repo.
_GH_FIELDS = (
    "number,title,url,headRefName,baseRefName,isDraft,author,createdAt,updatedAt,"
    "mergeable,files,closingIssuesReferences,labels"
)

# GitLab's closing keywords, the ones that close an issue when the request merges.
_CLOSING = re.compile(
    r"\b(?:clos(?:e|es|ed|ing)|fix(?:es|ed|ing)?|resolv(?:e|es|ed|ing)|implement(?:s|ed|ing)?)"
    r"\s*:?\s+#(\d+)",
    re.IGNORECASE,
)
_DIFF_HEADER = re.compile(r"^diff --git a/(?P<old>.+) b/(?P<new>.+)$")
_GH_MERGEABLE = {"MERGEABLE": "clean", "CONFLICTING": "conflicting"}


class InventoryError(Exception):
    """A platform CLI was absent, failed, or answered something unreadable."""


def build_list_command(platform: str, *, limit: int) -> list[str]:
    """Return the argv listing open requests on *platform*.

    >>> build_list_command("gitlab", limit=5)
    ['glab', 'mr', 'list', '--output', 'json', '--per-page', '5']
    """
    if platform == "github":
        return [
            "gh", "pr", "list", "--state", "open",
            "--json", _GH_FIELDS, "--limit", str(limit),
        ]  # fmt: skip
    return ["glab", "mr", "list", "--output", "json", "--per-page", str(limit)]


def build_diff_command(iid: int) -> list[str]:
    """Return the argv printing GitLab merge request *iid*'s diff in git's own format.

    >>> build_diff_command(12)
    ['glab', 'mr', 'diff', '12', '--raw']
    """
    return ["glab", "mr", "diff", str(iid), "--raw"]


def build_issue_state_command(platform: str, number: int) -> list[str]:
    """Return the argv reading issue *number*'s state.

    >>> build_issue_state_command("github", 7)
    ['gh', 'issue', 'view', '7', '--json', 'state']
    """
    if platform == "github":
        return ["gh", "issue", "view", str(number), "--json", "state"]
    return ["glab", "issue", "view", str(number), "--output", "json"]


def run_cli(command: list[str], target_dir: Path) -> str:
    """Run *command* in *target_dir* and return its stdout.

    Raises:
        InventoryError: the binary is missing or exited non-zero.
    """
    binary = shutil.which(command[0])
    if binary is None:
        raise InventoryError(f"{command[0]} is not installed")
    result = subprocess.run(  # nosec B603
        [binary, *command[1:]], cwd=str(target_dir), capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise InventoryError(detail[0] if detail else f"{command[0]} failed")
    return result.stdout


def run_json(command: list[str], target_dir: Path) -> Any:
    """Run *command* and parse its stdout as JSON.

    Raises:
        InventoryError: as `run_cli`, or the output was not JSON.
    """
    stdout = run_cli(command, target_dir)
    try:
        return json.loads(stdout or "null")
    except json.JSONDecodeError as exc:
        raise InventoryError(f"{command[0]} did not answer JSON: {exc}") from exc


def closing_references(text: str) -> list[int]:
    """The issue numbers *text* closes with one of GitLab's closing keywords, in order.

    A bare mention is not a closing reference — only a keyword in front of it is:

    >>> closing_references("Closes #12. Fixes: #3, see #9; resolved #12")
    [12, 3]
    """
    seen: dict[int, None] = {}
    for match in _CLOSING.finditer(text):
        seen.setdefault(int(match.group(1)), None)
    return list(seen)


def parse_diff(diff: str) -> list[dict[str, Any]]:
    """Reduce a git-format *diff* to ``[{path, additions, deletions}]``, one per file.

    The path is the *new* side's, so a rename is reported where it lands:

    >>> text = "diff --git a/x.py b/y.py\\n--- a/x.py\\n+++ b/y.py\\n+new\\n-old\\n+more\\n"
    >>> parse_diff(text)
    [{'path': 'y.py', 'additions': 2, 'deletions': 1}]
    """
    files: list[dict[str, Any]] = []
    for line in diff.splitlines():
        header = _DIFF_HEADER.match(line)
        if header:
            files.append({"path": header.group("new"), "additions": 0, "deletions": 0})
        elif files and not line.startswith(("+++", "---")):
            if line.startswith("+"):
                files[-1]["additions"] += 1
            elif line.startswith("-"):
                files[-1]["deletions"] += 1
    return files


def days_between(earlier: str, now: datetime) -> int | None:
    """Whole days from the ISO timestamp *earlier* to *now*, or None when unparseable.

    Both forges' spellings — GitHub's ``Z`` and GitLab's milliseconds — are read:

    >>> now = datetime(2026, 10, 9, tzinfo=UTC)
    >>> days_between("2026-10-01T12:00:00Z", now), days_between("2026-10-02T00:00:00.123Z", now)
    (7, 6)
    >>> days_between("", now) is None
    True
    """
    try:
        then = datetime.fromisoformat(earlier.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now - then).days


def _text(raw: dict[str, Any], key: str) -> str:
    """*raw*'s value at *key* as a string, with a missing or null value as ``''``.

    >>> _text({"a": None}, "a"), _text({"a": 3}, "a")
    ('', '3')
    """
    return str(raw.get(key) or "")


def _count(raw: dict[str, Any], key: str) -> int:
    """*raw*'s value at *key* as an int, with a missing or null value as ``0``."""
    return int(raw.get(key) or 0)


def _common(raw: dict[str, Any], keys: dict[str, str]) -> dict[str, Any]:
    """The text fields both forges carry, read through *keys* (shared name -> forge key)."""
    return {shared: _text(raw, key) for shared, key in keys.items()}


_GH_KEYS = {
    "title": "title",
    "url": "url",
    "branch": "headRefName",
    "base": "baseRefName",
    "created": "createdAt",
    "updated": "updatedAt",
}
_GL_KEYS = {
    "title": "title",
    "url": "web_url",
    "branch": "source_branch",
    "base": "target_branch",
    "created": "created_at",
    "updated": "updated_at",
}


def normalize_github(raw: dict[str, Any]) -> dict[str, Any]:
    """One `gh pr list` object in the shared vocabulary."""
    files = [
        {
            "path": _text(f, "path"),
            "additions": _count(f, "additions"),
            "deletions": _count(f, "deletions"),
        }
        for f in raw.get("files") or []
    ]
    return {
        "id": raw.get("number"),
        **_common(raw, _GH_KEYS),
        "draft": bool(raw.get("isDraft")),
        "author": _text(raw.get("author") or {}, "login"),
        "mergeable": _GH_MERGEABLE.get(_text(raw, "mergeable").upper(), "unknown"),
        "labels": [_text(label, "name") for label in raw.get("labels") or []],
        "files": files,
        "closes": [ref.get("number") for ref in raw.get("closingIssuesReferences") or []],
        "closes_source": "forge",
    }


def _gitlab_mergeable(raw: dict[str, Any]) -> str:
    """``has_conflicts`` read as `mergeable`; absent, ``unknown`` rather than a guess.

    >>> [_gitlab_mergeable(r) for r in ({"has_conflicts": True}, {"has_conflicts": False}, {})]
    ['conflicting', 'clean', 'unknown']
    """
    conflicts = raw.get("has_conflicts")
    if conflicts is None:
        return "unknown"
    return "conflicting" if conflicts else "clean"


def normalize_gitlab(raw: dict[str, Any], files: list[dict[str, Any]]) -> dict[str, Any]:
    """One `glab mr list` object in the shared vocabulary, with *files* from its diff.

    ``has_conflicts`` is the nearest GitLab has to GitHub's ``mergeable``.
    """
    return {
        "id": raw.get("iid"),
        **_common(raw, _GL_KEYS),
        "draft": bool(raw.get("draft") or raw.get("work_in_progress")),
        "author": _text(raw.get("author") or {}, "username"),
        "mergeable": _gitlab_mergeable(raw),
        "labels": list(raw.get("labels") or []),
        "files": files,
        "closes": closing_references(_text(raw, "description")),
        "closes_source": "description",
    }


def overlaps(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every pair of requests changing a file in common, with the files they share.

    >>> a = {"id": 1, "files": [{"path": "x"}, {"path": "y"}]}
    >>> b = {"id": 2, "files": [{"path": "y"}]}
    >>> c = {"id": 3, "files": [{"path": "z"}]}
    >>> overlaps([a, b, c])
    [{'a': 1, 'b': 2, 'files': ['y']}]
    """
    found = []
    for first, second in itertools.combinations(requests, 2):
        shared = {f["path"] for f in first["files"]} & {f["path"] for f in second["files"]}
        if shared:
            found.append({"a": first["id"], "b": second["id"], "files": sorted(shared)})
    return found


def issue_state(platform: str, number: int, target_dir: Path) -> str:
    """Issue *number*'s state as ``open``, ``closed``, or ``unknown`` when it cannot be read.

    Unreadable is not closed: a reference to an issue in another project, or one the
    token cannot see, must not make a request look obsolete.
    """
    try:
        payload = run_json(build_issue_state_command(platform, number), target_dir) or {}
    except InventoryError:
        return "unknown"
    state = str(payload.get("state") or "").lower()
    return {"opened": "open", "open": "open", "closed": "closed"}.get(state, "unknown")


def _fetch(platform: str, target_dir: Path, limit: int) -> list[dict[str, Any]]:
    """Ask the forge for its open requests, normalised, files included."""
    listing = run_json(build_list_command(platform, limit=limit), target_dir) or []
    if platform == "github":
        return [normalize_github(raw) for raw in listing]
    return [
        normalize_gitlab(raw, parse_diff(run_cli(build_diff_command(raw["iid"]), target_dir)))
        for raw in listing
    ]


def _annotate(
    request: dict[str, Any], platform: str, target_dir: Path, now: datetime
) -> dict[str, Any]:
    """Add the derived facts: size, age, idle time, and which closing references closed."""
    request["additions"] = sum(f["additions"] for f in request["files"])
    request["deletions"] = sum(f["deletions"] for f in request["files"])
    request["age_days"] = days_between(request["created"], now)
    request["idle_days"] = days_between(request["updated"], now)
    request["closes_closed"] = [
        number
        for number in request["closes"]
        if issue_state(platform, number, target_dir) == "closed"
    ]
    return request


def collect(
    target_dir: Path, *, limit: int, dry_run: bool = False, now: datetime | None = None
) -> dict[str, Any]:
    """Return the inventory for *target_dir*'s open requests.

    Raises:
        PlatformError: the platform could not be determined.
        InventoryError: the platform CLI failed.
    """
    platform = detect_platform(target_dir)
    command = build_list_command(platform, limit=limit)
    report: dict[str, Any] = {"platform": platform, "command": command, "requests": []}
    report["overlaps"] = []
    if dry_run:
        return report
    moment = now or datetime.now(UTC)
    requests = [
        _annotate(request, platform, target_dir, moment)
        for request in _fetch(platform, target_dir, limit)
    ]
    report["requests"] = requests
    report["overlaps"] = overlaps(requests)
    return report


def _render_request(request: dict[str, Any]) -> list[str]:
    """The text lines for one request."""
    flags = [request["mergeable"]] + (["draft"] if request["draft"] else [])
    lines = [
        f"#{request['id']}  {request['title']}",
        f"    {request['branch']} -> {request['base']}  by {request['author'] or '?'}"
        f"  [{', '.join(flags)}]",
        f"    age {request['age_days']}d, idle {request['idle_days']}d, "
        f"{len(request['files'])} files, +{request['additions']}/-{request['deletions']}",
    ]
    if request["closes"]:
        closed = request["closes_closed"]
        suffix = f"  (already closed: {', '.join(f'#{n}' for n in closed)})" if closed else ""
        lines.append(f"    closes {', '.join(f'#{n}' for n in request['closes'])}{suffix}")
    return lines


def render(report: dict[str, Any]) -> str:
    """Return *report* as text."""
    lines = [f"platform {report['platform']}", f"command  {' '.join(report['command'])}", ""]
    if not report["requests"]:
        lines.append("no open requests")
    for request in report["requests"]:
        lines.extend(_render_request(request))
    if report["overlaps"]:
        lines += ["", "overlapping files:"]
        for pair in report["overlaps"]:
            lines.append(f"  #{pair['a']} & #{pair['b']}: {', '.join(pair['files'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, gather the inventory, print it, and return an exit code."""
    parser = argparse.ArgumentParser(
        description="List open requests with the files, size and state a merge order needs."
    )
    parser.add_argument("--target-dir", default=".", help="Repository root (default: cwd).")
    parser.add_argument("--limit", type=int, default=50, help="Maximum requests to fetch.")
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the report as JSON."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the argv without running it.")
    args = parser.parse_args(argv)

    try:
        report = collect(Path(args.target_dir).resolve(), limit=args.limit, dry_run=args.dry_run)
    except PlatformError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_NO_PLATFORM
    except InventoryError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_CLI_FAILED

    print(json.dumps(report, indent=2) if args.json_output else render(report))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
