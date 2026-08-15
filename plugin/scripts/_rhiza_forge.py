#!/usr/bin/env python3
"""Which forge a repository is hosted on, and a read-only way to ask git.

Two entry points need this and neither may guess: ``platform_cli.py`` picks between
`gh` and `glab` before it *writes* anything (a PR, an issue, a release), and
``pr_status.py`` picks between them before it *reads* CI state. Both start from the same
question — what is `origin`? — and both get the same wrong answer if it is answered
loosely.

The detection lived inside ``platform_cli.py`` while it was the only caller. It is here
now because the alternative was the second caller copying it, and ``classify_host`` is
not a function to have two of: it is the piece that refuses ``github.com.evil.example``,
a host that embeds a known domain without being a subdomain of one. A copy that drifts
from this one acts against the wrong forge, which is strictly worse than refusing to act.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path

_KNOWN_HOSTS = {"github.com": "github", "gitlab.com": "gitlab"}

# `git@host:owner/repo` and `scheme://[user@]host/owner/repo`, the two spellings a
# remote is written in.
_SSH_REMOTE = re.compile(r"git@([^:]+):")
_URL_REMOTE = re.compile(r"[a-zA-Z]+://(?:[^@]+@)?([^/]+)/")


class PlatformError(Exception):
    """The hosting platform could not be determined."""


def git_stdout(target_dir: Path, args: list[str]) -> str:
    """Run a read-only git command in *target_dir*, returning stdout ('' on failure).

    ``GIT_TERMINAL_PROMPT=0`` so a repo whose remote wants credentials fails fast
    instead of blocking a non-interactive run on a password prompt.
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
    url = git_stdout(target_dir, ["remote", "get-url", "origin"])
    if not url:
        raise PlatformError("no `origin` remote — cannot tell which platform to use")
    match = _SSH_REMOTE.match(url) or _URL_REMOTE.match(url)
    if match is None:
        raise PlatformError(f"could not parse a host from origin: {url}")
    platform = classify_host(match.group(1))
    if platform is None:
        raise PlatformError(
            f"unsupported host {match.group(1)!r} — only GitHub and GitLab are handled"
        )
    return platform


def current_branch(target_dir: Path) -> str | None:
    """Return the branch checked out in *target_dir*, or None when there is none.

    ``symbolic-ref`` rather than ``rev-parse --abbrev-ref``: the caller uses this to
    find *the request for the branch you are on*, so the two cases that must not be
    confused are a detached HEAD (no branch — ``rev-parse`` answers the literal string
    ``HEAD``, which is a plausible-looking branch name) and a branch with no commits on
    it yet (a branch, which ``rev-parse`` fails outright on). ``symbolic-ref`` gets both
    right.
    """
    return git_stdout(target_dir, ["symbolic-ref", "--short", "HEAD"]) or None
