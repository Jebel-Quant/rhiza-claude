#!/usr/bin/env python3
"""Report open pull/merge requests and what CI on the origin said about them.

`/rhiza:quality` files issues, those issues become branches, and the branches become
requests that were green on the author's machine. The gap this closes is what happens
next: **local green and origin green are different claims**, and only the second one
merges. A `make test` that passes on macOS with a warm cache says nothing about a
matrix job on Windows, a lockfile the runner resolves differently, or a gate the repo
runs only in CI.

Asking the forge is the deterministic half of answering that, and it is deterministic
in the way that hurts — the two CLIs disagree about **shape**, not just about flags:

    gh   pr list --json statusCheckRollup  -> per-check objects, two different
                                              __typenames, SCREAMING_CASE conclusions
    glab mr list -F json                   -> the MRs, with no pipeline in sight;
         ci get --merge-request <iid>         the pipeline is a second call, and its
                                              status is lower-case

So this normalises both into one vocabulary — ``pass``/``fail``/``pending``/``skipped``/
``cancelled``/``unknown`` — and reports, per request, a rollup plus the individual
checks. **GitHub's answer is per job; GitLab's is per pipeline**, because a pipeline's
job list is not a shape this has been able to verify against a real GitLab, and
inventing one is how ``glab mr create --description-file`` shipped. That asymmetry is
reported rather than smoothed over: every check carries the exact drill-down command
for its platform, and on GitLab that command is the one that lists the failing jobs.

**It reads; it never retries, cancels or pushes.** Deciding what a red job means, and
fixing it, is `/rhiza:remote`'s job and needs judgement this cannot have.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/pr_status.py [--target-dir DIR] [--branch B | --all] [--limit N]
                           [--json] [--dry-run]

With neither ``--branch`` nor ``--all``, the branch currently checked out is used; on a
detached HEAD that falls back to every open request, which is what ``--all`` asks for
explicitly.

Exit codes:
  0  the forge answered (whatever it said about CI), or --dry-run rendered
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
from _rhiza_forge import PlatformError, current_branch, detect_platform  # noqa: E402

EXIT_OK = 0
EXIT_CLI_FAILED = 1
EXIT_USAGE = 2

SUCCESS = "pass"
FAILURE = "fail"
PENDING = "pending"
SKIPPED = "skipped"
CANCELLED = "cancelled"
UNKNOWN = "unknown"

# Worst-first. The rollup is the first state present, so a request with one failing job
# reads `fail` however many green ones surround it, and a still-running one is never
# reported as green just because everything finished so far has passed.
_PRECEDENCE = (FAILURE, PENDING, CANCELLED, UNKNOWN, SUCCESS, SKIPPED)

# GitHub answers a completed CheckRun with a `conclusion`; anything not listed is a
# state this has not seen, which is `unknown` rather than a guessed pass.
_GITHUB_CONCLUSIONS = {
    "SUCCESS": SUCCESS,
    "NEUTRAL": SUCCESS,
    "SKIPPED": SKIPPED,
    "CANCELLED": CANCELLED,
    "FAILURE": FAILURE,
    "TIMED_OUT": FAILURE,
    "STARTUP_FAILURE": FAILURE,
    "ACTION_REQUIRED": FAILURE,
    "STALE": UNKNOWN,
}
# A commit status (an external CI posting to the statuses API) has no conclusion — just
# a state, and a different vocabulary for it.
_GITHUB_STATES = {
    "SUCCESS": SUCCESS,
    "EXPECTED": PENDING,
    "PENDING": PENDING,
    "ERROR": FAILURE,
    "FAILURE": FAILURE,
}
# GitLab pipeline statuses, from the pipelines API. `manual` is a pipeline waiting for
# somebody to press a button, which is pending on a human rather than on a runner — but
# pending either way, and not something to report as green.
_GITLAB_STATUSES = {
    "success": SUCCESS,
    "failed": FAILURE,
    "canceled": CANCELLED,
    "canceling": CANCELLED,
    "skipped": SKIPPED,
    "created": PENDING,
    "waiting_for_resource": PENDING,
    "preparing": PENDING,
    "pending": PENDING,
    "running": PENDING,
    "manual": PENDING,
    "scheduled": PENDING,
}

# The fields `gh pr list --json` is asked for. Spelled out rather than globbed: gh errors
# on an unknown field, so this list is itself a contract with the CLI.
_GH_FIELDS = "number,title,headRefName,url,isDraft,statusCheckRollup"


class ForgeQueryError(Exception):
    """A platform CLI was absent, unauthenticated, or answered something unreadable."""


def build_list_command(platform: str, *, branch: str | None, limit: int) -> list[str]:
    """Return the argv listing open requests, optionally narrowed to one *branch*."""
    if platform == "github":
        command = ["gh", "pr", "list", "--state", "open", "--json", _GH_FIELDS]
        command += ["--limit", str(limit)]
        return [*command, "--head", branch] if branch else command
    command = ["glab", "mr", "list", "--output", "json", "--per-page", str(limit)]
    return [*command, "--source-branch", branch] if branch else command


def build_pipeline_command(iid: int | str) -> list[str]:
    """Return the argv for the head pipeline of GitLab merge request *iid*.

    ``--merge-request`` rather than ``--branch`` deliberately: GitLab's detached
    merge-request pipelines run against ``refs/merge-requests/<iid>/head``, so a
    request whose head pipeline has diverged from its source branch would otherwise be
    reported against a pipeline that is not the one gating the merge.
    """
    return ["glab", "ci", "get", "--merge-request", str(iid), "--output", "json"]


def _run_id(details_url: str) -> str | None:
    """Extract the workflow-run id from a GitHub check's details URL.

    The URL is ``…/actions/runs/<run>/job/<job>``. A commit status posted by an external
    CI has no such URL, and there is no `gh` command to fetch its log — so None here
    means "the log lives somewhere gh cannot reach", not "no log".
    """
    parts = details_url.split("/")
    if "runs" not in parts:
        return None
    index = parts.index("runs") + 1
    return parts[index] if index < len(parts) else None


def build_logs_command(platform: str, check: dict[str, Any]) -> list[str] | None:
    """Return the argv that drills into a failing *check*, or None when there is none.

    Emitted rather than executed. A failed job's log is routinely megabytes, and which
    part of it matters is exactly the judgement this script does not make — so the
    command is handed to the caller, whose job is to read the answer.
    """
    if platform == "github":
        run = _run_id(check.get("url") or "")
        return ["gh", "run", "view", run, "--log-failed"] if run else None
    pipeline = check.get("pipeline_id")
    if pipeline is None:
        return None
    return [
        "glab", "ci", "get", "--pipeline-id", str(pipeline),
        "--status", "failed", "--with-job-details",
    ]  # fmt: skip


def normalize_github_check(entry: dict[str, Any]) -> dict[str, Any]:
    """Reduce one ``statusCheckRollup`` entry to ``{name, state, url, raw}``.

    Two shapes arrive in the same array. A ``CheckRun`` is a GitHub Actions job and
    carries ``status``/``conclusion``; a ``StatusContext`` is an external CI posting to
    the statuses API and carries ``context``/``state``. Reading the second with the
    first's keys yields a nameless check in an unknown state, which is how an external
    required check comes to be invisible in a report that claims to be complete.
    """
    if entry.get("__typename") == "StatusContext":
        return _status_context(entry)
    return _check_run(entry)


def _status_context(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalise a commit status — an external CI posting to the statuses API."""
    raw = str(entry.get("state") or "")
    return {
        "name": entry.get("context") or "(unnamed status)",
        "state": _GITHUB_STATES.get(raw.upper(), UNKNOWN),
        "url": entry.get("targetUrl") or "",
        "raw": raw,
    }


def _check_run(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalise a GitHub Actions job.

    An unfinished job has no ``conclusion`` at all, so its ``status`` is what gets
    reported — reading the missing conclusion instead would file every in-flight job
    under ``unknown`` and bury the ones that genuinely are.
    """
    workflow = entry.get("workflowName") or ""
    name = entry.get("name") or "(unnamed check)"
    completed = str(entry.get("status") or "").upper() == "COMPLETED"
    raw = str(entry.get("conclusion" if completed else "status") or "")
    return {
        "name": f"{name} ({workflow})" if workflow else name,
        "state": _GITHUB_CONCLUSIONS.get(raw.upper(), UNKNOWN) if completed else PENDING,
        "url": entry.get("detailsUrl") or "",
        "raw": raw,
    }


def normalize_gitlab_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    """Reduce a GitLab pipeline object to a single check.

    One check per *pipeline*, not per job. `glab ci get` can be asked for job details,
    but the shape it prints them in is not something this has been able to check
    against a live GitLab — and a normaliser written from a guess is the exact bug that
    shipped a `glab` flag which did not exist. The rollup below is honest at pipeline
    granularity, and ``build_logs_command`` hands back the command that opens the jobs.
    """
    raw = str(payload.get("status") or "")
    pipeline_id = payload.get("id")
    return {
        "name": f"pipeline #{pipeline_id}" if pipeline_id else "pipeline",
        "state": _GITLAB_STATUSES.get(raw.lower(), UNKNOWN),
        "url": payload.get("web_url") or "",
        "raw": raw,
        "pipeline_id": pipeline_id,
    }


def rollup(checks: list[dict[str, Any]]) -> str:
    """Reduce a request's checks to one state; ``unknown`` when it has none.

    No checks at all is *not* a pass. A request whose workflow never triggered — a
    misspelled path filter, a workflow file that fails to parse — shows a clean check
    list, and reporting that as green is how it gets merged.
    """
    present = {check["state"] for check in checks}
    return next((state for state in _PRECEDENCE if state in present), UNKNOWN)


def _cli_json(target_dir: Path, command: list[str]) -> Any:
    """Run *command* and parse its stdout as JSON, or raise ``ForgeQueryError``."""
    # The resolved path, not the bare name — see the same call in `platform_cli.run` for
    # why the two differ on Windows.
    executable = shutil.which(command[0])
    if executable is None:
        raise ForgeQueryError(f"{command[0]} is not installed — cannot read CI state")
    result = subprocess.run(  # nosec B603
        [executable, *command[1:]], cwd=str(target_dir), capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise ForgeQueryError(f"{' '.join(command)} failed: {result.stderr.strip()[:300]}")
    try:
        return json.loads(result.stdout or "null")
    except ValueError as exc:
        raise ForgeQueryError(f"{command[0]} returned output that is not JSON") from exc


def _github_requests(target_dir: Path, command: list[str]) -> list[dict[str, Any]]:
    """Every open PR the *command* lists, each with its normalised checks."""
    requests = []
    for entry in _cli_json(target_dir, command) or []:
        checks = [normalize_github_check(c) for c in entry.get("statusCheckRollup") or []]
        requests.append(
            {
                "id": entry.get("number"),
                "title": entry.get("title") or "",
                "branch": entry.get("headRefName") or "",
                "url": entry.get("url") or "",
                "draft": bool(entry.get("isDraft")),
                "state": rollup(checks),
                "checks": checks,
            }
        )
    return requests


def _gitlab_requests(target_dir: Path, command: list[str]) -> list[dict[str, Any]]:
    """Every open MR the *command* lists, each with its head pipeline as one check.

    The pipeline is a second call per request, so a request whose pipeline cannot be
    read reports ``unknown`` and keeps going: one MR with no pipeline yet must not cost
    the caller the report on all the others.
    """
    requests = []
    for entry in _cli_json(target_dir, command) or []:
        iid = entry.get("iid")
        try:
            pipeline = _cli_json(target_dir, build_pipeline_command(iid)) or {}
        except ForgeQueryError:
            pipeline = {}
        checks = [normalize_gitlab_pipeline(pipeline)] if pipeline else []
        requests.append(
            {
                "id": iid,
                "title": entry.get("title") or "",
                "branch": entry.get("source_branch") or "",
                "url": entry.get("web_url") or "",
                "draft": bool(entry.get("draft")),
                "state": rollup(checks),
                "checks": checks,
            }
        )
    return requests


def collect(
    target_dir: Path,
    *,
    branch: str | None,
    limit: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Query the forge for *target_dir* and return the normalised report."""
    platform = detect_platform(target_dir)
    command = build_list_command(platform, branch=branch, limit=limit)
    summary: dict[str, Any] = {
        "platform": platform,
        "branch": branch,
        "command": command,
        "dry_run": dry_run,
        "requests": [],
        "notes": [],
    }
    if dry_run:
        summary["notes"].append("dry run — nothing was executed")
        return summary

    reader = _github_requests if platform == "github" else _gitlab_requests
    summary["requests"] = reader(target_dir, command)
    for request in summary["requests"]:
        for check in request["checks"]:
            check["logs_command"] = build_logs_command(platform, check)
    return summary


_MARK = {
    SUCCESS: "✓",
    FAILURE: "✗",
    PENDING: "•",
    SKIPPED: "–",
    CANCELLED: "⊘",
    UNKNOWN: "?",
}


def render(summary: dict[str, Any]) -> str:
    """Render *summary* as the human report."""
    lines = [f"platform {summary['platform']}", f"command  {' '.join(summary['command'])}"]
    if not summary["requests"] and not summary["dry_run"]:
        lines.append("")
        lines.append("no open requests matched — nothing is waiting on CI")
    for request in summary["requests"]:
        draft = " [draft]" if request["draft"] else ""
        lines.append("")
        lines.append(
            f"#{request['id']} {request['state'].upper()}{draft}  {request['title']}"
            f"\n  {request['branch']}  {request['url']}"
        )
        lines += [f"  {line}" for line in _render_checks(request["checks"])]
    lines += [f"note     {note}" for note in summary["notes"]]
    return "\n".join(lines)


def _render_checks(checks: list[dict[str, Any]]) -> list[str]:
    """Render one request's checks, with a drill-down line under each failing one."""
    if not checks:
        return ["(no checks reported — did a workflow ever trigger?)"]
    lines = []
    for check in checks:
        mark = _MARK.get(check["state"], "?")
        lines.append(f"{mark} {check['name']}  {check['url']}".rstrip())
        command = check.get("logs_command")
        if check["state"] == FAILURE and command:
            lines.append(f"    logs: {' '.join(command)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    """Entry point: report the open requests' CI state and return an exit code."""
    parser = argparse.ArgumentParser(description="Report open requests and their CI state.")
    parser.add_argument("--target-dir", default=".", help="Repository root (default: cwd).")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--branch", default=None, help="Only the request for this branch.")
    scope.add_argument(
        "--all", action="store_true", help="Every open request, not just this branch's."
    )
    parser.add_argument("--limit", type=int, default=20, help="Maximum requests to fetch.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the query without running it."
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the report as JSON."
    )
    args = parser.parse_args(argv)

    target_dir = Path(args.target_dir).resolve()
    branch = None if args.all else (args.branch or current_branch(target_dir))
    try:
        summary = collect(target_dir, branch=branch, limit=args.limit, dry_run=args.dry_run)
    except PlatformError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ForgeQueryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CLI_FAILED

    print(json.dumps(summary, indent=2) if args.json_output else render(summary))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
