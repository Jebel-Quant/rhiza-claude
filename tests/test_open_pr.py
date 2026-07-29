"""Tests for the PR/MR opener (`scripts/open_pr.py`).

This is the file that makes GitLab testable. While the `gh`/`glab` mapping lived in
command prose nothing executed it, so `/update` shipped with no GitLab branch at all —
it detected GitLab, offered `gitlab-project`, then called `gh pr create`. That was
fixed by reading, with nothing to confirm the fix.

Here the CLIs are stubbed on PATH and the exact argv is asserted for both platforms,
so a wrong subcommand or a swapped flag name fails a test instead of a user's release.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import open_pr
import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _git(repo: Path, *args: str) -> None:
    """Run a git command, raising with output on failure."""
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)}:\n{result.stderr}"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with a body file and no remote yet."""
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "BODY.md").write_text("## Summary\n\nbody\n")
    return tmp_path


def _remote(repo: Path, url: str) -> None:
    """Point `origin` at *url*."""
    _git(repo, "remote", "add", "origin", url)


@pytest.fixture
def stub_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Put fake `gh`/`glab` on PATH that record their argv and print a URL.

    This is what the prose version could never have: a way to observe the invocation.
    """
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    log = tmp_path / "invocations.txt"

    def install(name: str, *, exit_code: int = 0, url: str = "https://example.test/1") -> None:
        script = bin_dir / name
        script.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "{name} $*" >> "{log}"\n'
            f'echo "{url}"\n'
            f"exit {exit_code}\n"
        )
        script.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    install.log = log  # type: ignore[attr-defined]
    return install


class TestPlatformError:
    """The error raised when the hosting platform cannot be determined."""

    def test_is_exception_with_message(self):
        err = open_pr.PlatformError("boom")
        assert isinstance(err, Exception)
        assert str(err) == "boom"


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
    assert open_pr.detect_platform(repo) == expected


def test_a_lookalike_host_is_not_taken_for_the_real_one(repo):
    """Opening a request against the wrong host is worse than refusing to."""
    _remote(repo, "https://github.com.evil.example/acme/widget")
    with pytest.raises(open_pr.PlatformError, match="unsupported host"):
        open_pr.detect_platform(repo)


def test_no_remote_is_an_error_not_a_guess(repo):
    with pytest.raises(open_pr.PlatformError, match="no `origin` remote"):
        open_pr.detect_platform(repo)


def test_an_unsupported_host_is_named(repo):
    _remote(repo, "https://bitbucket.org/acme/widget")
    with pytest.raises(open_pr.PlatformError, match="bitbucket.org"):
        open_pr.detect_platform(repo)


def test_an_unparseable_remote_is_reported(repo):
    _remote(repo, "some-local-path")
    with pytest.raises(open_pr.PlatformError, match="could not parse a host"):
        open_pr.detect_platform(repo)


# --- the mapping itself: the part that had no GitLab branch -------------------


def test_github_create_argv():
    assert open_pr.build_command(
        "github", base="main", head="feat", title="T", body_file="B.md", update=False
    ) == ["gh", "pr", "create", "--base", "main", "--head", "feat", "--title", "T",
          "--body-file", "B.md"]  # fmt: skip


def test_gitlab_create_argv_uses_its_own_subcommand_and_flag_names():
    """`mr` not `pr`; `--target-branch`/`--source-branch`; `--description-file`."""
    assert open_pr.build_command(
        "gitlab", base="main", head="feat", title="T", body_file="B.md", update=False
    ) == ["glab", "mr", "create", "--target-branch", "main", "--source-branch", "feat",
          "--title", "T", "--description-file", "B.md"]  # fmt: skip


def test_github_update_argv():
    assert open_pr.build_command(
        "github", base="main", head="feat", title="T", body_file="B.md", update=True
    ) == ["gh", "pr", "edit", "feat", "--body-file", "B.md"]


def test_gitlab_update_argv():
    assert open_pr.build_command(
        "gitlab", base="main", head="feat", title="T", body_file="B.md", update=True
    ) == ["glab", "mr", "update", "feat", "--description-file", "B.md"]


def test_the_two_platforms_never_share_a_flag_name_by_accident():
    """A swapped flag is the failure this mapping exists to prevent."""
    gh = open_pr.build_command("github", base="m", head="h", title="T", body_file="B", update=False)
    glab = open_pr.build_command(
        "gitlab", base="m", head="h", title="T", body_file="B", update=False
    )
    assert "--base" in gh and "--base" not in glab
    assert "--target-branch" in glab and "--target-branch" not in gh
    assert "--body-file" in gh and "--body-file" not in glab
    assert "--description-file" in glab and "--description-file" not in gh


# --- executing, with the CLI stubbed -----------------------------------------


def test_gitlab_invocation_is_actually_made(repo, stub_cli):
    """The assertion that was previously impossible: glab really gets called."""
    _remote(repo, "https://gitlab.com/grp/proj.git")
    stub_cli("glab", url="https://gitlab.com/grp/proj/-/merge_requests/7")

    result = open_pr.open_pr(repo, base="main", head="feat", title="T", body_file="BODY.md")

    assert result["exit_code"] == open_pr.EXIT_OK
    assert result["platform"] == "gitlab"
    assert result["url"] == "https://gitlab.com/grp/proj/-/merge_requests/7"
    invoked = stub_cli.log.read_text()
    assert "glab mr create" in invoked
    assert "--source-branch feat" in invoked
    assert "--description-file BODY.md" in invoked


def test_github_invocation_is_actually_made(repo, stub_cli):
    _remote(repo, "https://github.com/acme/widget.git")
    stub_cli("gh", url="https://github.com/acme/widget/pull/3")

    result = open_pr.open_pr(repo, base="main", head="feat", title="T", body_file="BODY.md")

    assert result["url"] == "https://github.com/acme/widget/pull/3"
    assert "gh pr create" in stub_cli.log.read_text()


def test_a_failing_cli_is_reported_not_swallowed(repo, stub_cli):
    _remote(repo, "https://gitlab.com/grp/proj.git")
    stub_cli("glab", exit_code=1)

    result = open_pr.open_pr(repo, base="main", head="feat", title="T", body_file="BODY.md")

    assert result["exit_code"] == open_pr.EXIT_CLI_FAILED
    assert any("glab failed" in n for n in result["notes"])


def test_a_missing_cli_points_at_the_manual_route(repo, monkeypatch):
    """The branch is already pushed by then, so this must not read as a hard failure."""
    _remote(repo, "https://gitlab.com/grp/proj.git")
    real_which = open_pr.shutil.which
    monkeypatch.setattr(
        open_pr.shutil, "which", lambda name: None if name == "glab" else real_which(name)
    )

    result = open_pr.open_pr(repo, base="main", head="feat", title="T", body_file="BODY.md")

    assert result["exit_code"] == open_pr.EXIT_CLI_FAILED
    assert any("open it manually" in n for n in result["notes"])


def test_dry_run_creates_nothing(repo, stub_cli):
    _remote(repo, "https://gitlab.com/grp/proj.git")
    stub_cli("glab")

    result = open_pr.open_pr(
        repo, base="main", head="feat", title="T", body_file="BODY.md", dry_run=True
    )

    assert result["exit_code"] == open_pr.EXIT_OK
    assert result["command"][0] == "glab"
    assert not stub_cli.log.exists(), "dry run invoked the CLI"


def test_output_without_a_url_is_not_an_error(repo, stub_cli):
    """Some CLI versions print nothing useful; the request was still created."""
    _remote(repo, "https://github.com/acme/widget.git")
    stub_cli("gh", url="created (no url printed)")

    result = open_pr.open_pr(repo, base="main", head="feat", title="T", body_file="BODY.md")

    assert result["exit_code"] == open_pr.EXIT_OK
    assert result["url"] is None


# --- main() / CLI -------------------------------------------------------------


def test_main_dry_run_renders_the_gitlab_command(repo, capsys):
    _remote(repo, "https://gitlab.com/grp/proj.git")
    rc = open_pr.main(
        ["--base", "main", "--head", "feat", "--title", "T", "--body-file", "BODY.md",
         "--target-dir", str(repo), "--dry-run"]
    )  # fmt: skip
    assert rc == open_pr.EXIT_OK
    out = capsys.readouterr().out
    assert "platform gitlab" in out
    assert "glab mr create --target-branch main --source-branch feat" in out


def test_main_json_output(repo, capsys):
    _remote(repo, "https://github.com/acme/widget.git")
    rc = open_pr.main(
        ["--base", "main", "--head", "feat", "--title", "T", "--body-file", "BODY.md",
         "--target-dir", str(repo), "--dry-run", "--json"]
    )  # fmt: skip
    assert rc == open_pr.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["platform"] == "github"
    assert payload["command"][:3] == ["gh", "pr", "create"]


def test_main_reports_an_undetectable_platform(repo, capsys):
    rc = open_pr.main(
        ["--base", "main", "--head", "feat", "--body-file", "BODY.md",
         "--target-dir", str(repo), "--dry-run"]
    )  # fmt: skip
    assert rc == open_pr.EXIT_USAGE
    assert "no `origin` remote" in capsys.readouterr().err


def test_main_requires_the_body_file_to_exist(repo, capsys):
    _remote(repo, "https://github.com/acme/widget.git")
    rc = open_pr.main(
        ["--base", "main", "--head", "feat", "--body-file", "missing.md",
         "--target-dir", str(repo)]
    )  # fmt: skip
    assert rc == open_pr.EXIT_USAGE
    assert "body file not found" in capsys.readouterr().err


def test_main_executes_when_not_a_dry_run(repo, stub_cli, capsys):
    _remote(repo, "https://gitlab.com/grp/proj.git")
    stub_cli("glab", url="https://gitlab.com/grp/proj/-/merge_requests/9")
    rc = open_pr.main(
        ["--base", "main", "--head", "feat", "--title", "T", "--body-file", "BODY.md",
         "--target-dir", str(repo)]
    )  # fmt: skip
    assert rc == open_pr.EXIT_OK
    assert "merge_requests/9" in capsys.readouterr().out
