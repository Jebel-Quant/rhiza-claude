"""Tests for the shared forge detection (`scripts/_rhiza_forge.py`).

These moved here from `test_platform_cli.py` when a second caller appeared. They are
worth keeping adjacent to nothing else: `classify_host` is the function that decides
which company's API a command is about to write to, and the lookalike-host case below
is the one where being wrong is worse than doing nothing at all.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import _rhiza_forge
import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _git(repo: Path, *args: str) -> None:
    """Run a git command, raising with output on failure."""
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)}:\n{result.stderr}"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with no remote yet."""
    _git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


def _remote(repo: Path, url: str) -> None:
    """Point `origin` at *url*."""
    _git(repo, "remote", "add", "origin", url)


class TestPlatformError:
    """The error raised when the hosting platform cannot be determined."""

    def test_is_exception_with_message(self):
        err = _rhiza_forge.PlatformError("boom")
        assert isinstance(err, Exception)
        assert str(err) == "boom"


# --- git_stdout ---------------------------------------------------------------


def test_git_stdout_returns_trimmed_output(repo):
    _remote(repo, "https://github.com/acme/widget.git")
    assert _rhiza_forge.git_stdout(repo, ["remote", "get-url", "origin"]) == (
        "https://github.com/acme/widget.git"
    )


def test_git_stdout_is_empty_when_git_fails(repo):
    """A failed read is "we don't know", never a partial answer the caller acts on."""
    assert _rhiza_forge.git_stdout(repo, ["remote", "get-url", "nope"]) == ""


# --- platform detection -------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@github.com:acme/widget.git", "github"),
        ("https://github.com/acme/widget", "github"),
        ("https://github.com/acme/widget.git", "github"),
        ("git@gitlab.com:grp/proj.git", "gitlab"),
        ("https://gitlab.com/grp/proj", "gitlab"),
        ("https://gitlab.corp.example/grp/proj", "gitlab"),  # self-hosted
        ("https://x@gitlab.com/grp/proj", "gitlab"),  # credentials in the URL
    ],
)
def test_detects_the_platform_from_the_remote(repo, url, expected):
    _remote(repo, url)
    assert _rhiza_forge.detect_platform(repo) == expected


def test_a_lookalike_host_is_not_taken_for_the_real_one(repo):
    """Acting against the wrong host is worse than refusing to."""
    _remote(repo, "https://github.com.evil.example/acme/widget")
    with pytest.raises(_rhiza_forge.PlatformError, match="unsupported host"):
        _rhiza_forge.detect_platform(repo)


def test_no_remote_is_an_error_not_a_guess(repo):
    with pytest.raises(_rhiza_forge.PlatformError, match="no `origin` remote"):
        _rhiza_forge.detect_platform(repo)


def test_an_unsupported_host_is_named(repo):
    _remote(repo, "https://bitbucket.org/acme/widget")
    with pytest.raises(_rhiza_forge.PlatformError, match="bitbucket.org"):
        _rhiza_forge.detect_platform(repo)


def test_an_unparseable_remote_is_reported(repo):
    _remote(repo, "some-local-path")
    with pytest.raises(_rhiza_forge.PlatformError, match="could not parse a host"):
        _rhiza_forge.detect_platform(repo)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("GitHub.com", "github"),
        ("github.com.", "github"),  # a trailing root-zone dot is still github.com
        ("gitlab.internal", "gitlab"),  # conventional self-hosted prefix
        ("example.com", None),
    ],
)
def test_classify_host_directly(host, expected):
    """The cases a remote URL cannot easily express, asserted on the function itself."""
    assert _rhiza_forge.classify_host(host) == expected


# --- current_branch -----------------------------------------------------------


def test_current_branch_reports_the_checked_out_branch(repo):
    """True before the first commit too — an unborn branch is still a branch."""
    assert _rhiza_forge.current_branch(repo) == "main"


def test_a_detached_head_is_no_branch(repo, tmp_path):
    """The caller wants "the request for the branch you are on" — there isn't one."""
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", "f.txt")
    _git(repo, "-c", "user.email=t@e.test", "-c", "user.name=T", "commit", "-qm", "init")
    _git(repo, "checkout", "-q", "--detach", "HEAD")
    assert _rhiza_forge.current_branch(repo) is None


def test_no_branch_when_git_cannot_answer(tmp_path):
    """Outside a repo `rev-parse` fails, and an empty answer is not a branch name."""
    assert _rhiza_forge.current_branch(tmp_path) is None
