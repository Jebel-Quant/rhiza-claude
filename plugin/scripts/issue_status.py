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
issue, not merely about flag names; ``_issue_forge`` owns that disagreement — the argv,
the subprocess and the per-platform keys — and this module sees issues only in the
shared vocabulary it normalises them into.

**One asymmetry is reported rather than smoothed over.** GitHub shares a number space
between issues and pull requests, so `#86` in an issue body may be either and both are
reachable from one lookup. GitLab does not: `#86` is an issue and `!86` a merge request.
So the dependency states this resolves are exact on GitHub, and on GitLab a reference
that is not an issue comes back ``unresolved`` rather than guessed at. An unresolved
reference pushes an issue toward *reported* rather than *fixed*, so the weaker path
degrades safe.

**It also reads the tracker's history, for `/rhiza:quality`.** A finding the user closed
last run — fixed, or declined as not worth doing — is not new because this run found it
again, and re-filing it is how a scoring command turns into noise. ``--state closed`` or
``--state all`` lists those too, each with its ``state`` and, on GitHub, the
``state_reason`` it was closed with (``completed``, ``not_planned``, ``duplicate``).
GitLab records no reason, so there it comes back empty rather than guessed. Only open
issues get the triage signals: they describe whether an issue *can be fixed*, which is a
question a closed one no longer asks.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/issue_status.py [--target-dir DIR] [--issue N] [--limit N]
                              [--label L] [--state open|closed|all]
                              [--json] [--dry-run]

Exit codes:
  0  the forge answered (including "no open issues"), or --dry-run rendered
  1  the platform CLI failed, is absent, or is not authenticated
  2  the platform could not be determined
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _issue_forge import (  # noqa: E402
    STATES,
    ForgeQueryError,
    build_issue_command,
    build_reference_commands,
    build_request_command,
    normalize,
    run_json,
)
from _issue_signals import signals  # noqa: E402
from _rhiza_forge import PlatformError, detect_platform  # noqa: E402
from _rhiza_lock import lock_path, previously_tracked  # noqa: E402

EXIT_OK = 0
EXIT_CLI_FAILED = 1
EXIT_NO_PLATFORM = 2

# States that mean a referenced issue or request is no longer in play.
_SETTLED = frozenset({"CLOSED", "MERGED", "closed", "merged"})


def managed_paths(target_dir: Path) -> set[str]:
    """The template-owned paths recorded in this repo's lock, or an empty set.

    A repo that is not rhiza-managed has no lock and therefore no template-owned
    paths — which is the right answer rather than an error, because an unmanaged repo
    owns everything in it. ``previously_tracked`` already returns an empty set for a
    lock that is absent or unreadable, so there is no second check here.
    """
    return {str(path) for path in previously_tracked(lock_path(target_dir, None))}


def resolve_references(platform: str, target_dir: Path, numbers: list[int]) -> dict[int, str]:
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
    state: str = "open",
) -> dict[str, Any]:
    """Gather the issues in *state*, the open ones with derived signals and a category.

    Raises:
        PlatformError: the hosting platform could not be determined.
        ForgeQueryError: a platform CLI was absent, failed, or was unauthenticated.
    """
    platform = detect_platform(target_dir)
    command = build_issue_command(platform, limit=limit, labels=labels, state=state)
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
        if issue["state"] == "closed":
            issue["signals"] = None
            issues.append(issue)
            continue
        issues.append(_enrich(issue, platform, target_dir, requests, owned))

    return {
        "platform": platform,
        "command": command,
        "dry_run": False,
        "state": state,
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
        lines.append("no issues" if report.get("state", "open") != "open" else "no open issues")
        return "\n".join(lines)
    for issue in report["issues"]:
        facts = issue["signals"]
        if facts is None:
            reason = issue.get("state_reason") or "reason unrecorded"
            lines.append(f"{'closed':11}  #{issue['id']}  {issue['title']}")
            lines.append(f"{'':13}{reason}")
            continue
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
        "--state",
        choices=STATES,
        default="open",
        help="Which issues to list; closed ones carry no triage signals (default: open).",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the report as JSON."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the argv without running it.")
    args = parser.parse_args(argv)

    target = Path(args.target_dir).resolve()
    try:
        report = collect(
            target,
            limit=args.limit,
            labels=args.label,
            only=args.issue,
            dry_run=args.dry_run,
            state=args.state,
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
