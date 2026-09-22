#!/usr/bin/env python3
"""List a repository's open issues and say which could be fixed without a judgement call.

`/rhiza:quality` files findings as issues, those issues become branches, and the
branches become requests. The plugin has had the first step and the last for some time —
`quality` writes the issues, `remote` looks after the requests once they exist — and
nothing in between. This is what `/rhiza:fix` reads in order to close that gap.

**It reads; it never branches, commits, pushes or comments.** Deciding what an issue is
worth and writing the fix is `/rhiza:fix`'s job, and needs judgement this cannot have.
The split is the same one `pr_status.py` draws against `/rhiza:remote`, for the same
reason.

Reading issues does not belong in ``platform_cli.py``, which maps a *write* onto `gh` or
`glab` and says so in its own docstring. The two CLIs disagree about the **shape** of an
issue, not merely about flag names, and there are five disagreements in a single object:

    gh   issue list --state open --json number,title,body,labels,author,createdAt,url
         -> {"number": 95, "body": "…", "labels": [{"name": "bug"}],
             "author": {"login": "tschm"}, "createdAt": "…", "url": "…"}

    glab issue list --output json --per-page 20
         -> {"iid": 95, "description": "…", "labels": ["bug"],
             "author": {"username": "tschm"}, "created_at": "…", "web_url": "…"}

Read with the other's keys, every one of those yields an empty body or a nameless issue
rather than an error — which is the failure mode `platform_cli.py` records having
shipped once already, when `/update` reached GitLab with a flag `glab` does not have.

**One asymmetry is reported rather than smoothed over.** GitHub shares a number space
between issues and pull requests, so `#86` in an issue body may be either and both are
reachable from one lookup. GitLab does not: `#86` is an issue and `!86` a merge request.
So the dependency states this resolves are exact on GitHub, and on GitLab a reference
that is not an issue comes back ``unresolved`` rather than guessed at. An unresolved
reference pushes an issue toward *reported* rather than *fixed*, so the weaker path
degrades safe.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/issue_status.py [--target-dir DIR] [--issue N] [--limit N]
                              [--label L] [--json] [--dry-run]

Exit codes:
  0  the forge answered (including "no open issues"), or --dry-run rendered
  1  the platform CLI failed, is absent, or is not authenticated
  2  the platform could not be determined
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _issue_signals import signals  # noqa: E402
from _rhiza_lock import lock_path, previously_tracked  # noqa: E402
from _rhiza_forge import PlatformError, detect_platform  # noqa: E402

EXIT_OK = 0
EXIT_CLI_FAILED = 1
EXIT_NO_PLATFORM = 2

# Spelled out rather than globbed: `gh` errors on an unknown field, so this list is
# itself a contract with the CLI and a typo here fails loudly instead of silently
# dropping a signal the triage depends on.
_GH_FIELDS = "number,title,body,labels,author,createdAt,updatedAt,url"
_GH_REQUEST_FIELDS = "number,title,body,url"

# States that mean a referenced issue or request is no longer in play.
_SETTLED = frozenset({"CLOSED", "MERGED", "closed", "merged"})


class ForgeQueryError(Exception):
    """A platform CLI was absent, unauthenticated, or answered something unreadable."""


def build_issue_command(platform: str, *, limit: int, labels: list[str]) -> list[str]:
    """Return the argv listing open issues, optionally narrowed to *labels*.

    >>> build_issue_command("github", limit=5, labels=[])[:4]
    ['gh', 'issue', 'list', '--state']

    GitLab's listing is open by default and takes its labels comma-joined, which is the
    second place these two CLIs stop lining up:

    >>> build_issue_command("gitlab", limit=5, labels=["bug", "docs"])[-2:]
    ['--label', 'bug,docs']
    """
    if platform == "github":
        command = ["gh", "issue", "list", "--state", "open", "--json", _GH_FIELDS]
        command += ["--limit", str(limit)]
        for label in labels:
            command += ["--label", label]
        return command
    command = ["glab", "issue", "list", "--output", "json", "--per-page", str(limit)]
    return [*command, "--label", ",".join(labels)] if labels else command


def build_request_command(platform: str, *, limit: int) -> list[str]:
    """Return the argv listing open requests, so an issue already being worked is seen.

    >>> build_request_command("gitlab", limit=3)
    ['glab', 'mr', 'list', '--output', 'json', '--per-page', '3']
    """
    if platform == "github":
        return [
            "gh", "pr", "list", "--state", "open",
            "--json", _GH_REQUEST_FIELDS, "--limit", str(limit),
        ]  # fmt: skip
    return ["glab", "mr", "list", "--output", "json", "--per-page", str(limit)]


def build_reference_commands(platform: str, number: int) -> list[list[str]]:
    """Return the argv candidates that resolve reference *number*, in order.

    On GitHub one number may name an issue or a pull request, and only trying tells
    you which — so both are returned and the first that answers wins. On GitLab a `#N`
    is always an issue, so there is exactly one candidate and a merge request reached
    this way is simply not found:

    >>> build_reference_commands("gitlab", 75)
    [['glab', 'issue', 'view', '75', '--output', 'json']]
    >>> len(build_reference_commands("github", 75))
    2
    """
    if platform == "github":
        return [
            ["gh", "issue", "view", str(number), "--json", "number,state,title"],
            ["gh", "pr", "view", str(number), "--json", "number,state,title"],
        ]
    return [["glab", "issue", "view", str(number), "--output", "json"]]


def run_json(command: list[str], target_dir: Path) -> Any:
    """Run *command* in *target_dir* and parse its stdout as JSON.

    Raises:
        ForgeQueryError: the binary is missing, it failed, or stdout was not JSON.
    """
    binary = shutil.which(command[0])
    if binary is None:
        raise ForgeQueryError(f"{command[0]} is not installed")
    result = subprocess.run(  # nosec B603
        [binary, *command[1:]],
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise ForgeQueryError(detail[0] if detail else f"{command[0]} failed")
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ForgeQueryError(f"{command[0]} did not answer JSON: {exc}") from exc


def _text(raw: dict[str, Any], key: str) -> str:
    """*raw*'s value at *key* as a string, with a missing or null value as ``''``."""
    return str(raw.get(key) or "")


def _normalize_github(raw: dict[str, Any]) -> dict[str, Any]:
    """One `gh issue list` object in the shared vocabulary."""
    return {
        "id": raw.get("number"),
        "title": _text(raw, "title"),
        "body": _text(raw, "body"),
        "labels": [label.get("name", "") for label in raw.get("labels") or []],
        "author": (raw.get("author") or {}).get("login", ""),
        "created": _text(raw, "createdAt"),
        "url": _text(raw, "url"),
    }


def _normalize_gitlab(raw: dict[str, Any]) -> dict[str, Any]:
    """One `glab issue list` object in the shared vocabulary.

    Five keys differ from GitHub's and none of them errors when read with the wrong
    name — `iid`/`number`, `description`/`body`, label strings against label objects,
    snake_case against camelCase, and `web_url`/`url`.
    """
    return {
        "id": raw.get("iid"),
        "title": _text(raw, "title"),
        "body": _text(raw, "description"),
        "labels": list(raw.get("labels") or []),
        "author": (raw.get("author") or {}).get("username", ""),
        "created": _text(raw, "created_at"),
        "url": _text(raw, "web_url"),
    }


def normalize(platform: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Return one issue in the shared vocabulary, whichever CLI produced it.

    The whole point is that both sides land on the same object:

    >>> gh = {"number": 95, "title": "t", "body": "b", "labels": [{"name": "bug"}],
    ...       "author": {"login": "tschm"}, "createdAt": "x", "url": "u"}
    >>> lab = {"iid": 95, "title": "t", "description": "b", "labels": ["bug"],
    ...        "author": {"username": "tschm"}, "created_at": "x", "web_url": "u"}
    >>> normalize("github", gh) == normalize("gitlab", lab)
    True
    """
    return _normalize_github(raw) if platform == "github" else _normalize_gitlab(raw)


def managed_paths(target_dir: Path) -> set[str]:
    """The template-owned paths recorded in this repo's lock, or an empty set.

    A repo that is not rhiza-managed has no lock and therefore no template-owned
    paths — which is the right answer rather than an error, because an unmanaged repo
    owns everything in it. ``previously_tracked`` already returns an empty set for a
    lock that is absent or unreadable, so there is no second check here.
    """
    return {str(path) for path in previously_tracked(lock_path(target_dir, None))}


def resolve_references(
    platform: str, target_dir: Path, numbers: list[int]
) -> dict[int, str]:
    """Map each of *numbers* to its state, or ``unresolved`` when it cannot be read.

    One lookup per number, and only dependency references reach here — an issue that
    merely cites a merged PR is not sequenced behind it, and resolving every mention
    would turn a well-annotated issue into a stale one.
    """
    states: dict[int, str] = {}
    for number in numbers:
        states[number] = "unresolved"
        for command in build_reference_commands(platform, number):
            try:
                payload = run_json(command, target_dir)
            except ForgeQueryError:
                continue
            state = str(payload.get("state") or "").strip()
            if state:
                states[number] = state
                break
    return states


def _requests_by_issue(requests: list[dict[str, Any]], issue_id: int) -> list[int]:
    """The open requests whose title or body mentions ``#issue_id``."""
    token = f"#{issue_id}"
    hits: list[Any] = []
    for request in requests:
        text = f"{request.get('title') or ''} {request.get('body') or ''}"
        if token in text:
            hits.append(request.get("number") or request.get("iid"))
    return [number for number in hits if number is not None]


def _enrich(
    issue: dict[str, Any],
    platform: str,
    target_dir: Path,
    requests: list[dict[str, Any]],
    owned: set[str],
) -> dict[str, Any]:
    """Attach the derived signals to one normalised *issue*, in place, and return it.

    Two passes over :func:`signals` deliberately: the first reads the paths out of the
    body so this can resolve them against the tree and the lock, and the second folds
    those answers back in. The alternative — a signals call that takes a repository —
    would put the filesystem inside the one module that has no business touching it.
    """
    body = str(issue["body"])
    named = [str(path) for path in signals(body)["paths"]]
    missing = tuple(path for path in named if not (target_dir / path).exists())
    template_owned = tuple(path for path in named if path in owned)
    open_requests = tuple(_requests_by_issue(requests, int(issue["id"])))
    states = resolve_references(platform, target_dir, list(signals(body)["dependencies"]))
    superseded = tuple(number for number, state in states.items() if state in _SETTLED)
    issue["reference_states"] = {str(k): v for k, v in states.items()}
    issue["signals"] = signals(
        body,
        template_owned=template_owned,
        missing=missing,
        open_requests=open_requests,
        superseded_by=superseded,
    )
    return issue


def collect(
    target_dir: Path,
    *,
    limit: int,
    labels: list[str],
    only: list[int],
    dry_run: bool,
) -> dict[str, Any]:
    """Gather every open issue with its derived signals and suggested category.

    Raises:
        PlatformError: the hosting platform could not be determined.
        ForgeQueryError: a platform CLI was absent, failed, or was unauthenticated.
    """
    platform = detect_platform(target_dir)
    command = build_issue_command(platform, limit=limit, labels=labels)
    if dry_run:
        return {"platform": platform, "command": command, "dry_run": True, "issues": []}

    raw_issues = run_json(command, target_dir)
    requests = run_json(build_request_command(platform, limit=limit), target_dir)
    owned = managed_paths(target_dir)
    notes: list[str] = []
    if platform == "gitlab":
        notes.append(
            "gitlab: `#N` names an issue, never a merge request — a reference to one "
            "comes back unresolved rather than guessed at"
        )

    issues: list[dict[str, Any]] = []
    for raw in raw_issues:
        issue = normalize(platform, raw)
        if only and issue["id"] not in only:
            continue
        issues.append(_enrich(issue, platform, target_dir, requests, owned))

    return {
        "platform": platform,
        "command": command,
        "dry_run": False,
        "notes": notes,
        "issues": issues,
    }


def render(report: dict[str, Any]) -> str:
    """The report as lines for a human reading over the command's shoulder."""
    if report.get("dry_run"):
        return " ".join(report["command"])
    lines = [f"platform     {report['platform']}"]
    for note in report.get("notes", []):
        lines.append(f"note         {note}")
    if not report["issues"]:
        lines.append("no open issues")
        return "\n".join(lines)
    for issue in report["issues"]:
        facts = issue["signals"]
        lines.append(f"{facts['category']:11}  #{issue['id']}  {issue['title']}")
        lines.append(f"{'':13}{_why(facts)}")
        for caution in facts["cautions"]:
            lines.append(f"{'':13}caution: {caution}")
    return "\n".join(lines)


def _why(facts: dict[str, Any]) -> str:
    """One line naming the signal that put an issue in its category.

    >>> _why({"category": "mechanical", "acceptance": "it works"})
    'acceptance criterion, single-valued'
    >>> _why({"category": "decision", "acceptance": None, "decide_markers": []})
    'no acceptance criterion — nobody has said what done means'
    """
    category = facts["category"]
    if category == "blocked":
        return f"already has an open request: {facts.get('open_requests')}"
    if category == "stale":
        return f"sequenced behind {facts['superseded_by']}, which has settled"
    if category == "decision":
        if facts.get("acceptance") is None:
            return "no acceptance criterion — nobody has said what done means"
        return f"hands the reader a choice: {', '.join(facts['decide_markers'])}"
    if category == "optional":
        return "acceptance criterion admits more than one outcome"
    return "acceptance criterion, single-valued"


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, gather the report, print it, and return an exit code."""
    parser = argparse.ArgumentParser(
        description="List open issues and say which need no judgement call to fix."
    )
    parser.add_argument("--target-dir", default=".", help="Repository root (default: cwd).")
    parser.add_argument(
        "--issue",
        action="append",
        type=int,
        default=[],
        help="Only this issue number; repeatable.",
    )
    parser.add_argument("--limit", type=int, default=20, help="Maximum issues to fetch.")
    parser.add_argument(
        "--label", action="append", default=[], help="Only issues with this label; repeatable."
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the report as JSON."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the argv without running it."
    )
    args = parser.parse_args(argv)

    target = Path(args.target_dir).resolve()
    try:
        report = collect(
            target,
            limit=args.limit,
            labels=args.label,
            only=args.issue,
            dry_run=args.dry_run,
        )
    except PlatformError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_NO_PLATFORM
    except ForgeQueryError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_CLI_FAILED

    print(json.dumps(report, indent=2) if args.json_output else render(report))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
