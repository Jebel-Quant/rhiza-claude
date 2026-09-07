#!/usr/bin/env python3
"""Block until the release bump is on the default branch, so one run can tag it.

`/rhiza:release` cannot tag what it has just built. A squash-merge replaces the release
branch's commits with a new one, so the commit worth tagging does not exist until the
request lands. That used to end the run: the user came back later and invoked the command
a second time, and the second invocation's whole job was to notice the merge had happened.
This is that same wait, held inside the one invocation.

**What it waits for is the bump landing, not a request merging.** Those are different
claims, and only the first one is the precondition for cutting a tag — a request can be
closed and re-landed by hand, merged with a title nobody recognises, or squashed into a
SHA no one predicted, and none of that changes what has to be true before the tag. So the
probe reads content off the remote branch itself:

    git show refs/remotes/origin/<branch>:CHANGELOG.md  -> newest `## [X.Y.Z]` heading

`CHANGELOG.md` rather than the declared version location, because the changelog section
is the one artifact **every** release commit carries: in every language, and on a
`dynamic = ["version"]` project whose manifest holds no version at all. It is also the
same fact `check_version_bump.py` reads to tell a merged-but-untagged release from a
fresh one — through the same parser, `_rhiza_changelog` — so the wait and the phase
check agree by construction rather than by luck.

No forge, no CLI, no auth: `git fetch` against `origin` is the entire mechanism. A repo
whose `gh`/`glab` is missing or logged out still gets the wait.

**The timeout is a hand-off, not a failure.** Review takes as long as it takes, and a
session does not outlive a weekend, so running out of time is an expected outcome with
its own exit code — the caller reports the open request and stops, and the release is
finished by re-running the command, which finds the merged bump and tags it. Nothing is
half-done at that point: the wait creates nothing.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/wait_for_merge.py --branch B --expect-version X.Y.Z [--target-dir DIR]
                                [--changelog FILE] [--timeout SECONDS]
                                [--interval SECONDS] [--json]

``--timeout 0`` polls exactly once, which is how to ask "has it landed?" without waiting.
The default waits nine minutes, which is what fits in one tool call; waiting longer is the
caller running this again, not a bigger number.

Exit codes:
  0  the bump is on the branch — the SHA to tag is in the summary
  1  git failed (no `origin`, no network, no such branch) — nothing was waited for
  2  usage: `--expect-version` is not X.Y.Z
  3  the timeout elapsed with the bump still not landed — hand back to the caller
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rhiza_changelog import newest_changelog_version  # noqa: E402

EXIT_LANDED = 0
EXIT_GIT_FAILED = 1
EXIT_USAGE = 2
EXIT_TIMEOUT = 3

# Nine minutes, because one call has to fit inside one tool call: an agent's Bash
# timeout caps out at ten. A caller who wants longer than this runs it again rather than
# raising it — see `/rhiza:release` step 11, which decides between the two by asking the
# forge whether the request's checks are still running.
DEFAULT_TIMEOUT = 540.0
DEFAULT_INTERVAL = 20.0
DEFAULT_CHANGELOG = "CHANGELOG.md"

# `origin` is not configurable here for the same reason it is not in `_rhiza_forge`:
# every command in this plugin pushes to, and reads from, that one remote.
REMOTE = "origin"

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def _git(target_dir: Path, args: list[str]) -> tuple[int, str, str]:
    """Run git in *target_dir*, returning ``(returncode, stdout, stderr)``.

    ``GIT_TERMINAL_PROMPT=0`` so a remote that wants credentials fails fast instead of
    blocking the poll on a password prompt nobody is there to answer.
    """
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(  # nosec B603
        [shutil.which("git") or "git", *args],
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def fetch_branch(target_dir: Path, branch: str) -> str:
    """Update ``refs/remotes/origin/<branch>``; return '' on success, else the error.

    The refspec is spelled out because a bare `git fetch origin <branch>` updates the
    remote-tracking ref only *opportunistically*, and everything below reads that ref by
    name.
    """
    code, _, err = _git(
        target_dir,
        ["fetch", "--quiet", REMOTE, f"+refs/heads/{branch}:refs/remotes/{REMOTE}/{branch}"],
    )
    if code == 0:
        return ""
    # git prints the useful line first and then two lines of general advice, so the last
    # line of a failed fetch is "and the repository exists." — true of every failure and
    # a diagnosis of none.
    lines = [line.strip() for line in err.splitlines() if line.strip()]
    fatal = next((line for line in lines if line.startswith(("fatal:", "error:"))), None)
    return (fatal or (lines[0] if lines else f"git fetch exited {code}"))[:300]


def landed_version(target_dir: Path, branch: str, changelog: str) -> str | None:
    """Return the newest changelog version on ``origin/<branch>``, or None.

    None covers both "no such file on that branch" and "no release heading in it", which
    the caller treats identically: neither is the version it is waiting for.
    """
    code, out, _ = _git(target_dir, ["show", f"refs/remotes/{REMOTE}/{branch}:{changelog}"])
    return newest_changelog_version(out) if code == 0 else None


def branch_sha(target_dir: Path, branch: str) -> str:
    """Return the commit SHA ``origin/<branch>`` points at, or '' if it won't resolve."""
    code, out, _ = _git(target_dir, ["rev-parse", f"refs/remotes/{REMOTE}/{branch}"])
    return out.strip() if code == 0 else ""


def _timeout_note(branch: str, expect: str, found: str | None, timeout: float) -> str:
    """Phrase the timeout in terms of what the branch actually carries."""
    carries = f"carries {found}" if found else "carries no release heading"
    return (
        f"{REMOTE}/{branch} still {carries} after {timeout:.0f}s, not {expect} — "
        "the request has not landed yet"
    )


def wait_for_landing(
    target_dir: Path,
    *,
    branch: str,
    expect: str,
    changelog: str = DEFAULT_CHANGELOG,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll ``origin/<branch>`` until its changelog names *expect*; summarise the wait.

    *sleep* and *clock* are injected because the shape of the loop — that it polls again
    after an interval, that it never sleeps past the deadline, that a git failure stops
    it at once — is the part worth testing, and it is unobservable in real time.
    """
    started = clock()
    summary: dict[str, Any] = {
        "branch": branch,
        "expect": expect,
        "status": "timeout",
        "found": None,
        "sha": None,
        "polls": 0,
        "elapsed": 0.0,
        "notes": [],
        "exit_code": EXIT_TIMEOUT,
    }
    while True:
        summary["polls"] += 1
        error = fetch_branch(target_dir, branch)
        if error:
            summary.update(status="error", exit_code=EXIT_GIT_FAILED, notes=[error])
            break
        found = landed_version(target_dir, branch, changelog)
        summary["found"] = found
        if found == expect:
            summary.update(
                status="landed", exit_code=EXIT_LANDED, sha=branch_sha(target_dir, branch)
            )
            break
        remaining = timeout - (clock() - started)
        if remaining <= 0:
            summary["notes"] = [_timeout_note(branch, expect, found, timeout)]
            break
        sleep(min(interval, remaining))
    summary["elapsed"] = round(clock() - started, 1)
    return summary


def _print_summary(summary: dict[str, Any]) -> None:
    """Render *summary* as the two or three lines a caller needs to read."""
    status = summary["status"]
    if status == "landed":
        print(f"landed  {REMOTE}/{summary['branch']} carries {summary['expect']}")
        print(f"commit  {summary['sha']}")
    elif status == "error":
        print(f"error   {summary['notes'][0]}", file=sys.stderr)
    else:
        print(f"waiting {summary['notes'][0]}", file=sys.stderr)
    print(f"polled  {summary['polls']}x over {summary['elapsed']}s")


def main(argv: list[str] | None = None) -> int:
    """Entry point: wait for the bump to land and return an exit code."""
    parser = argparse.ArgumentParser(
        description="Wait for a release bump to land on the default branch."
    )
    parser.add_argument("--target-dir", default=".", help="Repository root (default: cwd).")
    parser.add_argument("--branch", required=True, help="The branch the release merges into.")
    parser.add_argument(
        "--expect-version", required=True, help="The version the merged changelog must name."
    )
    parser.add_argument(
        "--changelog", default=DEFAULT_CHANGELOG, help="Changelog path on that branch."
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Seconds to wait before handing back (0 polls once).",
    )
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL, help="Seconds between polls."
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    expect = args.expect_version.strip().lstrip("v")
    if not _SEMVER.match(expect):
        print(f"error: {args.expect_version!r} is not a version (expected X.Y.Z)", file=sys.stderr)
        return EXIT_USAGE

    summary = wait_for_landing(
        Path(args.target_dir).resolve(),
        branch=args.branch,
        expect=expect,
        changelog=args.changelog,
        timeout=max(args.timeout, 0.0),
        interval=max(args.interval, 1.0),
    )
    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        _print_summary(summary)
    exit_code: int = summary["exit_code"]
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
