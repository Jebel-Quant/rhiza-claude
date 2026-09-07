"""Tests for the release wait (`scripts/wait_for_merge.py`).

The claim under test is narrow and load-bearing: **the bump is on the default branch**.
That is the precondition for cutting a tag, and `/rhiza:release` used to establish it by
ending the run and having a human come back later. Now one invocation waits for it, so
what the wait actually observes has to be right — a wait that reports "landed" a moment
early would tag a commit the merge is about to replace.

So the probe runs against real git: a real `origin`, a real fetch, a real
`git show origin/main:CHANGELOG.md`. Only the clock is fake, because the loop's shape —
it polls again, it never sleeps past its deadline, a git failure stops it at once — is
unobservable in real time and is the rest of what matters here.

What a release heading *looks like* is not tested here: that parser is shared with
`check_version_bump.py`'s phase decision and is covered in
`test__rhiza_changelog.py`, which is the point of it being shared.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import wait_for_merge as wfm

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")

_CHANGELOG = "# Changelog\n\n## [{version}] - 2026-01-01\n\n- something\n"


def _git(repo: Path, *args: str) -> None:
    """Run a git command, raising with output on failure."""
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)}:\n{result.stderr}"


def _init(repo: Path) -> None:
    """Initialise *repo* on `main` with an identity, so commits are possible."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")


def _release(repo: Path, version: str, *, changelog: str = "CHANGELOG.md") -> None:
    """Commit a changelog whose newest section names *version*."""
    (repo / changelog).write_text(_CHANGELOG.format(version=version), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"chore: release v{version}")


@pytest.fixture
def upstream(tmp_path: Path) -> Path:
    """A repo standing in for the forge, with v1.3.0 released on `main`."""
    repo = tmp_path / "upstream"
    _init(repo)
    _release(repo, "1.3.0")
    return repo


@pytest.fixture
def local(tmp_path: Path, upstream: Path) -> Path:
    """A repo whose `origin` is *upstream* and which has fetched nothing yet."""
    repo = tmp_path / "local"
    _init(repo)
    _git(repo, "remote", "add", "origin", str(upstream))
    return repo


class _Clock:
    """A fake monotonic clock that only advances when something sleeps.

    Injecting this rather than patching `time` keeps every assertion about the loop
    exact: elapsed time is the sum of the sleeps the loop chose, so `slept` below *is*
    the schedule under test.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        """Record a sleep and advance the clock by it."""
        self.slept.append(seconds)
        self.now += seconds

    def __call__(self) -> float:
        """Return the current fake time."""
        return self.now


# --- the git probes, against real git ----------------------------------------


def test_fetch_populates_the_remote_tracking_ref(local):
    """The explicit refspec is what makes `origin/main` readable by name afterwards."""
    assert wfm.fetch_branch(local, "main") == ""
    assert wfm.branch_sha(local, "main") != ""


def test_fetch_reports_a_missing_remote_rather_than_hanging(tmp_path):
    """No `origin` is an error to hand back, not something to keep polling."""
    repo = tmp_path / "no-remote"
    _init(repo)
    assert "origin" in wfm.fetch_branch(repo, "main").lower()


def test_fetch_reports_a_branch_the_remote_does_not_have(local):
    """A wrong `--branch` fails immediately instead of waiting out the timeout."""
    assert wfm.fetch_branch(local, "trunk") != ""


def test_fetch_falls_back_to_the_exit_code_when_git_says_nothing(local, monkeypatch):
    """A silent failure still produces a note — an empty message reports as nothing."""
    monkeypatch.setattr(wfm, "_git", lambda *_a, **_k: (128, "", "   \n"))
    assert wfm.fetch_branch(local, "main") == "git fetch exited 128"


def test_the_landed_version_is_read_off_the_remote_branch(local):
    """What the probe answers is the remote's content, not the local tree's."""
    wfm.fetch_branch(local, "main")
    assert wfm.landed_version(local, "main", "CHANGELOG.md") == "1.3.0"


def test_a_changelog_absent_from_that_branch_is_simply_not_landed(local):
    """A missing file and an unlanded release are the same answer: not it yet."""
    wfm.fetch_branch(local, "main")
    assert wfm.landed_version(local, "main", "docs/CHANGELOG.md") is None


def test_a_changelog_with_no_release_heading_is_not_landed(local, upstream):
    """A file that exists but names no version is not evidence of a release."""
    (upstream / "CHANGELOG.md").write_text("# Changelog\n\nnothing yet\n", encoding="utf-8")
    _git(upstream, "commit", "-aqm", "docs: empty changelog")
    wfm.fetch_branch(local, "main")
    assert wfm.landed_version(local, "main", "CHANGELOG.md") is None


def test_the_sha_of_an_unknown_branch_is_empty(local):
    """Nothing invents a SHA — an unresolvable ref answers with no SHA at all."""
    assert wfm.branch_sha(local, "nope") == ""


# --- the wait itself ----------------------------------------------------------


def test_a_release_already_on_the_branch_lands_on_the_first_poll(local, upstream):
    """The wait is also the probe: a merged release needs no waiting at all."""
    _release(upstream, "1.4.0")
    clock = _Clock()
    summary = wfm.wait_for_landing(
        local, branch="main", expect="1.4.0", sleep=clock.sleep, clock=clock
    )
    assert summary["status"] == "landed"
    assert summary["exit_code"] == wfm.EXIT_LANDED
    assert summary["polls"] == 1
    assert clock.slept == []
    assert summary["sha"] == wfm.branch_sha(local, "main")


def test_it_notices_the_merge_on_a_later_poll(local, upstream):
    """The point of the loop: the release lands while it is waiting, and it sees it."""
    clock = _Clock()

    def sleep(seconds: float) -> None:
        """Sleep, and on the second one let the release land upstream."""
        clock.sleep(seconds)
        if len(clock.slept) == 2:
            _release(upstream, "1.4.0")

    summary = wfm.wait_for_landing(
        local, branch="main", expect="1.4.0", interval=10, timeout=600, sleep=sleep, clock=clock
    )
    assert summary["status"] == "landed"
    assert summary["polls"] == 3
    assert clock.slept == [10, 10]
    assert summary["elapsed"] == 20.0


def test_the_timeout_hands_back_and_says_what_the_branch_carries(local):
    """Running out of time is an outcome with a report, not an exception."""
    clock = _Clock()
    summary = wfm.wait_for_landing(
        local,
        branch="main",
        expect="1.4.0",
        interval=30,
        timeout=100,
        sleep=clock.sleep,
        clock=clock,
    )
    assert summary["status"] == "timeout"
    assert summary["exit_code"] == wfm.EXIT_TIMEOUT
    assert summary["found"] == "1.3.0"
    assert "carries 1.3.0" in summary["notes"][0]
    assert "1.4.0" in summary["notes"][0]
    assert summary["sha"] is None


def test_it_never_sleeps_past_its_deadline(local):
    """The last sleep is shortened to the remaining time, so `--timeout` is honoured."""
    clock = _Clock()
    summary = wfm.wait_for_landing(
        local,
        branch="main",
        expect="1.4.0",
        interval=30,
        timeout=70,
        sleep=clock.sleep,
        clock=clock,
    )
    assert clock.slept == [30, 30, 10]
    assert summary["elapsed"] == 70.0


def test_a_zero_timeout_polls_exactly_once(local):
    """ "Has it landed?" is the same code path with no waiting in it."""
    clock = _Clock()
    summary = wfm.wait_for_landing(
        local, branch="main", expect="1.4.0", timeout=0, sleep=clock.sleep, clock=clock
    )
    assert summary["polls"] == 1
    assert clock.slept == []
    assert summary["status"] == "timeout"


def test_a_timeout_on_a_branch_with_no_changelog_says_so(local):
    """The note distinguishes "carries an older release" from "carries none"."""
    clock = _Clock()
    summary = wfm.wait_for_landing(
        local,
        branch="main",
        expect="1.4.0",
        changelog="MISSING.md",
        timeout=0,
        sleep=clock.sleep,
        clock=clock,
    )
    assert "no release heading" in summary["notes"][0]


def test_a_git_failure_stops_the_wait_at_once(tmp_path):
    """A misconfigured remote is not something to keep retrying for half an hour."""
    repo = tmp_path / "no-remote"
    _init(repo)
    clock = _Clock()
    summary = wfm.wait_for_landing(
        repo, branch="main", expect="1.4.0", timeout=3600, sleep=clock.sleep, clock=clock
    )
    assert summary["status"] == "error"
    assert summary["exit_code"] == wfm.EXIT_GIT_FAILED
    assert summary["polls"] == 1
    assert clock.slept == []
    assert summary["notes"]


# --- reporting ----------------------------------------------------------------


def test_the_landed_summary_prints_the_commit_to_tag(capsys):
    """The SHA is the whole reason the caller waited, so it is on stdout."""
    wfm._print_summary(
        {
            "branch": "main",
            "expect": "1.4.0",
            "status": "landed",
            "sha": "abc123",
            "polls": 2,
            "elapsed": 40.0,
            "notes": [],
        }
    )
    out = capsys.readouterr().out
    assert "landed" in out
    assert "abc123" in out


@pytest.mark.parametrize("status", ["timeout", "error"])
def test_a_wait_that_did_not_land_reports_on_stderr(capsys, status):
    """Neither outcome is a result to be piped into something else."""
    wfm._print_summary(
        {
            "branch": "main",
            "expect": "1.4.0",
            "status": status,
            "sha": None,
            "polls": 3,
            "elapsed": 60.0,
            "notes": ["something to say"],
        }
    )
    captured = capsys.readouterr()
    assert "something to say" in captured.err
    assert "polled  3x" in captured.out


# --- the CLI ------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["nightly", "1.4", "v1.4.0.1", "", "latest"])
def test_a_version_that_is_not_a_version_is_a_usage_error(local, capsys, raw):
    """The caller passes `${TARGET#v}`; anything else is a mistake worth stopping on."""
    code = wfm.main(["--target-dir", str(local), "--branch", "main", "--expect-version", raw])
    assert code == wfm.EXIT_USAGE
    assert "is not a version" in capsys.readouterr().err


def test_the_cli_accepts_a_v_prefix(local, upstream, capsys):
    """`v1.4.0` and `1.4.0` name the same release; neither is a reason to fail."""
    _release(upstream, "1.4.0")
    code = wfm.main(
        [
            "--target-dir",
            str(local),
            "--branch",
            "main",
            "--expect-version",
            "v1.4.0",
            "--timeout",
            "0",
        ]
    )
    assert code == wfm.EXIT_LANDED
    assert "carries 1.4.0" in capsys.readouterr().out


def test_the_cli_emits_json_for_a_landed_release(local, upstream, capsys):
    """The JSON shape is what a caller reads the SHA out of."""
    _release(upstream, "1.4.0")
    code = wfm.main(
        [
            "--target-dir",
            str(local),
            "--branch",
            "main",
            "--expect-version",
            "1.4.0",
            "--timeout",
            "0",
            "--json",
        ]
    )
    assert code == wfm.EXIT_LANDED
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "landed"
    assert payload["sha"] == wfm.branch_sha(local, "main")


def test_the_cli_returns_the_timeout_code_without_waiting(local, capsys):
    """A negative timeout is clamped to a single poll rather than looping forever."""
    code = wfm.main(
        [
            "--target-dir",
            str(local),
            "--branch",
            "main",
            "--expect-version",
            "1.4.0",
            "--timeout",
            "-5",
            "--interval",
            "0",
        ]
    )
    assert code == wfm.EXIT_TIMEOUT
    captured = capsys.readouterr()
    assert "has not landed yet" in captured.err
    assert "polled  1x" in captured.out


def test_the_cli_returns_the_git_failure_code(tmp_path, capsys):
    """Exit 1 is "nothing was waited for", which is a different fact from a timeout."""
    repo = tmp_path / "no-remote"
    _init(repo)
    code = wfm.main(
        ["--target-dir", str(repo), "--branch", "main", "--expect-version", "1.4.0", "--json"]
    )
    assert code == wfm.EXIT_GIT_FAILED
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_the_default_timeout_fits_inside_one_tool_call():
    """Nine minutes, because an agent's Bash timeout caps at ten and this call blocks.

    A default that cannot complete is worse than a short one: the wait would be killed
    mid-poll and the caller would read the kill as a failure rather than as "not yet".
    """
    assert wfm.DEFAULT_TIMEOUT <= 600 - wfm.DEFAULT_INTERVAL
