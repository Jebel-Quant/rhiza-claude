#!/usr/bin/env python3
"""Open or update a pull/merge request — the platform mapping behind `/init` and `/update`.

GitHub and GitLab do the same thing with different subcommands *and* different flag
names, and that mapping used to live in command prose:

    gh   pr create  --base B --head H   --title T --body-file F
    glab mr create  --target-branch B --source-branch H --title T --description-file F

Prose is the wrong home for it. Nothing executes prose in a test, so the mapping was
unverifiable — and it showed: `/update` shipped with **no GitLab branch at all**,
detecting GitLab, offering `gitlab-project`, then calling `gh pr create` and failing.
That bug was fixed by reading, with nothing to confirm the fix.

Here the mapping is code, so a test can stub `gh`/`glab` on PATH and assert the exact
argv for each platform. The platform is detected from the `origin` remote using
label-boundary matching, so a lookalike host is never taken for the real one.

`--dry-run` prints the argv without executing, which is also how the tests check the
mapping without any CLI installed at all.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/open_pr.py --base BRANCH --head BRANCH --title T --body-file F \
      [--target-dir DIR] [--update] [--dry-run] [--json]

Exit codes:
  0  opened, updated, or (with --dry-run) rendered
  1  the platform CLI failed
  2  the platform could not be determined, or a required file is missing
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

_KNOWN_HOSTS = {"github.com": "github", "gitlab.com": "gitlab"}

EXIT_OK = 0
EXIT_CLI_FAILED = 1
EXIT_USAGE = 2


class PlatformError(Exception):
    """The hosting platform could not be determined."""


def _git(target_dir: Path, args: list[str]) -> str:
    """Run a read-only git command, returning stdout ('' on failure)."""
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
    return result.stdout.strip() if result.returncode == 0 else ""


def classify_host(host: str) -> str | None:
    """Return ``github``/``gitlab`` for *host*, or None when it is neither.

    Label-boundary matching, so ``github.com.evil.example`` — which embeds a known
    domain without being a subdomain of it — is not taken for GitHub. Self-hosted
    GitLab conventionally lives at ``gitlab.<company>.<tld>``.
    """
    h = host.lower().rstrip(".")
    for domain, platform in _KNOWN_HOSTS.items():
        if h == domain or h.endswith(f".{domain}"):
            return platform
        if domain in h:
            return None
    return "gitlab" if h.split(".", 1)[0] == "gitlab" else None


def detect_platform(target_dir: Path) -> str:
    """Return the hosting platform for *target_dir*'s `origin` remote."""
    url = _git(target_dir, ["remote", "get-url", "origin"])
    if not url:
        raise PlatformError("no `origin` remote — cannot tell which platform to use")
    match = re.match(r"git@([^:]+):", url) or re.match(r"[a-zA-Z]+://(?:[^@]+@)?([^/]+)/", url)
    if match is None:
        raise PlatformError(f"could not parse a host from origin: {url}")
    platform = classify_host(match.group(1))
    if platform is None:
        raise PlatformError(
            f"unsupported host {match.group(1)!r} — only GitHub and GitLab are handled"
        )
    return platform


def build_command(
    platform: str, *, base: str, head: str, title: str, body_file: str, update: bool
) -> list[str]:
    """Return the argv that opens (or updates) the request on *platform*.

    The whole point of this function: the two CLIs disagree on the subcommand, on how
    the branches are named, and on what the body flag is called.
    """
    if platform == "github":
        if update:
            return ["gh", "pr", "edit", head, "--body-file", body_file]
        return [
            "gh", "pr", "create",
            "--base", base, "--head", head,
            "--title", title, "--body-file", body_file,
        ]  # fmt: skip
    if update:
        return ["glab", "mr", "update", head, "--description-file", body_file]
    return [
        "glab", "mr", "create",
        "--target-branch", base, "--source-branch", head,
        "--title", title, "--description-file", body_file,
    ]  # fmt: skip


def open_pr(
    target_dir: Path,
    *,
    base: str,
    head: str,
    title: str,
    body_file: str,
    update: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Open or update the request; return a summary dict."""
    platform = detect_platform(target_dir)
    command = build_command(
        platform, base=base, head=head, title=title, body_file=body_file, update=update
    )

    summary: dict[str, Any] = {
        "platform": platform,
        "command": command,
        "dry_run": dry_run,
        "url": None,
        "notes": [],
        "exit_code": EXIT_OK,
    }
    if dry_run:
        summary["notes"].append("dry run — nothing was created")
        return summary

    if shutil.which(command[0]) is None:
        summary.update(
            exit_code=EXIT_CLI_FAILED,
            notes=[f"{command[0]} is not installed — push the branch and open it manually"],
        )
        return summary

    result = subprocess.run(  # nosec B603
        command, cwd=str(target_dir), capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        summary.update(
            exit_code=EXIT_CLI_FAILED,
            notes=[f"{command[0]} failed: {result.stderr.strip()[:300]}"],
        )
        return summary

    url = next(
        (line.strip() for line in result.stdout.splitlines() if line.strip().startswith("http")),
        None,
    )
    summary["url"] = url
    return summary


def main(argv: list[str] | None = None) -> int:
    """Entry point: open or update the request and return an exit code."""
    parser = argparse.ArgumentParser(description="Open or update a pull/merge request.")
    parser.add_argument("--base", required=True, help="Branch to merge into.")
    parser.add_argument("--head", required=True, help="Branch holding the work.")
    parser.add_argument("--title", default="", help="Request title (ignored with --update).")
    parser.add_argument("--body-file", required=True, help="File holding the body.")
    parser.add_argument("--target-dir", default=".", help="Repository root (default: cwd).")
    parser.add_argument(
        "--update", action="store_true", help="Update an existing request instead of creating one."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the command without running it."
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    target_dir = Path(args.target_dir).resolve()
    if not args.dry_run and not (target_dir / args.body_file).is_file():
        if not Path(args.body_file).is_file():
            print(f"error: body file not found: {args.body_file}", file=sys.stderr)
            return EXIT_USAGE

    try:
        summary = open_pr(
            target_dir,
            base=args.base,
            head=args.head,
            title=args.title,
            body_file=args.body_file,
            update=args.update,
            dry_run=args.dry_run,
        )
    except PlatformError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        print(f"platform {summary['platform']}")
        print(f"command  {' '.join(summary['command'])}")
        if summary["url"]:
            print(f"url      {summary['url']}")
        for note in summary["notes"]:
            stream = sys.stdout if summary["exit_code"] == EXIT_OK else sys.stderr
            print(f"note     {note}", file=stream)
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
