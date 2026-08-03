"""Tests for the forge mapping (`scripts/platform_cli.py`).

This is the file that makes GitLab testable. While the `gh`/`glab` mapping lived in
command prose nothing executed it, so `/update` shipped with no GitLab branch at all —
it detected GitLab, offered `gitlab-project`, then called `gh pr create`.

The lesson from the *second* bug matters more. After the mapping was extracted, it still
passed `--description-file` to `glab mr create` — a flag glab has never had — and this
file passed anyway, because stubbing the CLI and asserting the argv the code produced
only ever proves the code agrees with itself. `test_every_long_flag_exists_in_the_real_cli`
is the fix: it reads the flags back out of `<cli> --help`, so the claim is checked
against the CLI rather than against us.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import platform_cli
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

    def install(
        name: str, *, exit_code: int = 0, url: str = "https://example.test/1", stdout: str = ""
    ) -> None:
        script = bin_dir / name
        script.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "{name} $*" >> "{log}"\n'
            f"{stdout or f'echo {url!r}'}\n"
            f"exit {exit_code}\n"
        )
        script.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    install.log = log  # type: ignore[attr-defined]
    return install


class TestPlatformError:
    """The error raised when the hosting platform cannot be determined."""

    def test_is_exception_with_message(self):
        err = platform_cli.PlatformError("boom")
        assert isinstance(err, Exception)
        assert str(err) == "boom"


class TestUnsupportedAction:
    """The error raised when an action has no equivalent on the detected platform."""

    def test_is_exception_with_message(self):
        err = platform_cli.UnsupportedAction("boom")
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
    assert platform_cli.detect_platform(repo) == expected


def test_a_lookalike_host_is_not_taken_for_the_real_one(repo):
    """Acting against the wrong host is worse than refusing to."""
    _remote(repo, "https://github.com.evil.example/acme/widget")
    with pytest.raises(platform_cli.PlatformError, match="unsupported host"):
        platform_cli.detect_platform(repo)


def test_no_remote_is_an_error_not_a_guess(repo):
    with pytest.raises(platform_cli.PlatformError, match="no `origin` remote"):
        platform_cli.detect_platform(repo)


def test_an_unsupported_host_is_named(repo):
    _remote(repo, "https://bitbucket.org/acme/widget")
    with pytest.raises(platform_cli.PlatformError, match="bitbucket.org"):
        platform_cli.detect_platform(repo)


def test_an_unparseable_remote_is_reported(repo):
    _remote(repo, "some-local-path")
    with pytest.raises(platform_cli.PlatformError, match="could not parse a host"):
        platform_cli.detect_platform(repo)


# --- the mapping, action by action --------------------------------------------

_BODY = "## Summary\n\nbody\n"

# The mapping, as one readable table. `%BODY%` stands in for the body text so each row
# stays on one line; the two platforms differ enough that seeing them adjacent is the
# whole value of writing it this way.
_EXPECTED = {
    ("github", "auth-status"): "gh auth status",
    ("gitlab", "auth-status"): "glab auth status",
    ("github", "repo-view"): "gh repo view --json defaultBranchRef,visibility",
    ("gitlab", "repo-view"): "glab repo view -F json",
    ("github", "pr-create"): ("gh pr create --base main --head feat --title T --body-file BODY.md"),
    ("gitlab", "pr-create"): (
        "glab mr create --target-branch main --source-branch feat --title T --description %BODY%"
    ),
    ("github", "pr-update"): "gh pr edit feat --body-file BODY.md",
    ("gitlab", "pr-update"): "glab mr update feat --description %BODY%",
    ("github", "issue-create"): "gh issue create --title T --body-file BODY.md",
    ("gitlab", "issue-create"): "glab issue create --title T --description %BODY%",
}


@pytest.mark.parametrize(("platform", "action"), sorted(_EXPECTED))
def test_the_argv_for_each_action_and_platform(platform, action):
    """One table, both platforms, every action — the mapping in a single readable place."""
    expected = [
        _BODY if word == "%BODY%" else word for word in _EXPECTED[(platform, action)].split()
    ]

    assert (
        platform_cli.build_command(
            platform,
            action,
            base="main",
            head="feat",
            title="T",
            body_file="BODY.md",
            body=_BODY,
        )
        == expected
    )


def test_gitlab_never_gets_a_file_flag_for_a_body():
    """The exact bug this rewrite fixes: `glab` has no `--description-file`.

    Against a real glab 1.110.0 that argv answers `Unknown flag: --description-file`.
    `mr create`, `mr update` and `issue create` all take the text inline.
    """
    for action in ("pr-create", "pr-update", "issue-create"):
        argv = platform_cli.build_command(
            "gitlab", action, base="m", head="h", title="T", body_file="B.md", body=_BODY
        )
        assert not [a for a in argv if a.endswith("-file")], f"{action}: {argv}"
        assert "--description" in argv
        assert _BODY in argv, "the body text itself must be on the command line"


def test_github_passes_the_path_and_never_the_text():
    """gh reads the file, so putting a multi-kilobyte body in argv would be pointless."""
    argv = platform_cli.build_command(
        "github", "pr-create", base="m", head="h", title="T", body_file="B.md", body=_BODY
    )
    assert "--body-file" in argv and "B.md" in argv
    assert _BODY not in argv


def test_release_create_generates_notes_on_github():
    assert platform_cli.build_command("github", "release-create", tag="v1.2.3") == [
        "gh", "release", "create", "v1.2.3", "--generate-notes",
    ]  # fmt: skip


def test_release_create_prefers_an_explicit_notes_file_on_github():
    assert platform_cli.build_command(
        "github", "release-create", tag="v1.2.3", notes_file="NOTES.md"
    ) == ["gh", "release", "create", "v1.2.3", "--notes-file", "NOTES.md"]


def test_release_create_on_gitlab_uses_its_notes_file_flag():
    """glab does have `-F/--notes-file` for releases — unlike issues and MRs."""
    assert platform_cli.build_command(
        "gitlab", "release-create", tag="v1.2.3", notes_file="NOTES.md"
    ) == ["glab", "release", "create", "v1.2.3", "--notes-file", "NOTES.md"]


def test_release_create_without_notes_is_refused_on_gitlab():
    """glab has no --generate-notes, and a silently note-less release is worse."""
    with pytest.raises(platform_cli.UnsupportedAction, match="--generate-notes"):
        platform_cli.build_command("gitlab", "release-create", tag="v1.2.3")


def test_the_two_platforms_never_share_a_flag_name_by_accident():
    """A swapped flag is the failure this mapping exists to prevent."""
    kwargs = {"base": "m", "head": "h", "title": "T", "body_file": "B", "body": _BODY}
    gh = platform_cli.build_command("github", "pr-create", **kwargs)
    glab = platform_cli.build_command("gitlab", "pr-create", **kwargs)
    assert "--base" in gh and "--base" not in glab
    assert "--target-branch" in glab and "--target-branch" not in gh
    assert "--body-file" in gh and "--body-file" not in glab
    assert "--description" in glab and "--description" not in gh


# --- checked against the real CLIs, not against ourselves ---------------------


def _long_flags_in_help(binary: str, subcommand: list[str]) -> set[str]:
    """Return the long flags `<binary> <subcommand> --help` documents."""
    result = subprocess.run(
        [binary, *subcommand, "--help"], capture_output=True, text=True, check=False
    )
    return set(re.findall(r"--[a-z][a-z0-9-]+", result.stdout + result.stderr))


@pytest.mark.parametrize(
    ("platform", "action"),
    [(p, a) for p in ("github", "gitlab") for a in platform_cli.ACTIONS],
)
def test_every_long_flag_exists_in_the_real_cli(platform, action):
    """Verify our argv against `--help`, which is the check that was missing.

    Stubbing a CLI and asserting the argv proves only that the code agrees with itself
    — and it did agree, all the way through shipping `glab mr create
    --description-file`, a flag that does not exist. Here the flags come back out of
    the CLI's own help text, so the mapping is checked against the tool.

    Skips when the binary is absent. `gh` is present on GitHub's runners, so the
    GitHub half runs in CI unconditionally; CI installs `glab` for the other half.
    """
    binary = {"github": "gh", "gitlab": "glab"}[platform]
    if shutil.which(binary) is None:
        pytest.skip(f"{binary} not installed")

    try:
        argv = platform_cli.build_command(
            platform,
            action,
            base="m",
            head="h",
            title="T",
            body_file="B.md",
            body=_BODY,
            tag="v1.0.0",
            notes_file="NOTES.md",
        )
    except platform_cli.UnsupportedAction:
        pytest.skip(f"{action} is not supported on {platform}")

    # Every action is `<binary> <group> <verb>`, so the first two non-flag words are
    # the subcommand whose help documents the flags.
    subcommand = [a for a in argv[1:] if not a.startswith("-")][:2]
    documented = _long_flags_in_help(binary, subcommand)
    used = {a for a in argv if a.startswith("--")}
    assert used <= documented, (
        f"{' '.join(argv[:3])} uses flag(s) {sorted(used - documented)} that "
        f"`{binary} {' '.join(subcommand)} --help` does not document"
    )


# --- repo-view normalisation --------------------------------------------------


def test_github_repo_view_is_normalised():
    """gh answers `PUBLIC`; a caller comparing raw values gets a platform-dependent answer."""
    assert platform_cli.normalize_repo_view(
        "github", {"defaultBranchRef": {"name": "main"}, "visibility": "PUBLIC"}
    ) == {"default_branch": "main", "visibility": "public"}


def test_gitlab_repo_view_is_normalised():
    """glab returns the Projects API object: snake_case keys, lower-case visibility."""
    assert platform_cli.normalize_repo_view(
        "gitlab", {"default_branch": "main", "visibility": "public"}
    ) == {"default_branch": "main", "visibility": "public"}


@pytest.mark.parametrize(
    ("platform", "payload"),
    [
        ("github", {}),
        ("github", {"defaultBranchRef": None}),
        ("gitlab", {}),
    ],
)
def test_an_empty_repo_view_yields_none_not_a_crash(platform, payload):
    """A brand-new repo has no default branch; that is a fact, not an error."""
    assert platform_cli.normalize_repo_view(platform, payload) == {
        "default_branch": None,
        "visibility": None,
    }


# --- executing, with the CLI stubbed -----------------------------------------


def test_gitlab_invocation_is_actually_made(repo, stub_cli):
    """The assertion that was previously impossible: glab really gets called."""
    _remote(repo, "https://gitlab.com/grp/proj.git")
    stub_cli("glab", url="https://gitlab.com/grp/proj/-/merge_requests/7")

    result = platform_cli.run(
        repo, "pr-create", base="main", head="feat", title="T", body_file="BODY.md", body=_BODY
    )

    assert result["exit_code"] == platform_cli.EXIT_OK
    assert result["platform"] == "gitlab"
    assert result["url"] == "https://gitlab.com/grp/proj/-/merge_requests/7"
    invoked = stub_cli.log.read_text()
    assert "glab mr create" in invoked
    assert "--source-branch feat" in invoked
    assert "--description-file" not in invoked


def test_github_invocation_is_actually_made(repo, stub_cli):
    _remote(repo, "https://github.com/acme/widget.git")
    stub_cli("gh", url="https://github.com/acme/widget/pull/3")

    result = platform_cli.run(
        repo, "pr-create", base="main", head="feat", title="T", body_file="BODY.md", body=_BODY
    )

    assert result["url"] == "https://github.com/acme/widget/pull/3"
    assert "gh pr create" in stub_cli.log.read_text()


def test_issue_create_returns_the_issue_url(repo, stub_cli):
    _remote(repo, "https://gitlab.com/grp/proj.git")
    stub_cli("glab", url="https://gitlab.com/grp/proj/-/issues/12")

    result = platform_cli.run(repo, "issue-create", title="T", body_file="BODY.md", body=_BODY)

    assert result["url"] == "https://gitlab.com/grp/proj/-/issues/12"
    assert "glab issue create" in stub_cli.log.read_text()


def test_auth_status_succeeds_when_logged_in(repo, stub_cli):
    _remote(repo, "https://github.com/acme/widget.git")
    stub_cli("gh")

    result = platform_cli.run(repo, "auth-status")

    assert result["exit_code"] == platform_cli.EXIT_OK
    assert "gh auth status" in stub_cli.log.read_text()


def test_auth_status_fails_when_logged_out(repo, stub_cli):
    """The preflight has to distinguish "no CLI" from "CLI, not logged in"."""
    _remote(repo, "https://gitlab.com/grp/proj.git")
    stub_cli("glab", exit_code=1)

    result = platform_cli.run(repo, "auth-status")

    assert result["exit_code"] == platform_cli.EXIT_CLI_FAILED
    assert any("glab failed" in n for n in result["notes"])


def test_repo_view_parses_and_normalises_real_output(repo, stub_cli):
    _remote(repo, "https://gitlab.com/grp/proj.git")
    stub_cli("glab", stdout='echo \'{"default_branch":"trunk","visibility":"private"}\'')

    result = platform_cli.run(repo, "repo-view")

    assert result["data"] == {"default_branch": "trunk", "visibility": "private"}


def test_repo_view_reports_non_json_output(repo, stub_cli):
    """A CLI that printed a warning instead of JSON must not read as "no default branch"."""
    _remote(repo, "https://github.com/acme/widget.git")
    stub_cli("gh", stdout="echo 'not json at all'")

    result = platform_cli.run(repo, "repo-view")

    assert result["exit_code"] == platform_cli.EXIT_CLI_FAILED
    assert result["data"] is None
    assert any("not JSON" in n for n in result["notes"])


def test_a_failing_cli_is_reported_not_swallowed(repo, stub_cli):
    _remote(repo, "https://gitlab.com/grp/proj.git")
    stub_cli("glab", exit_code=1)

    result = platform_cli.run(
        repo, "pr-create", base="main", head="feat", title="T", body_file="BODY.md", body=_BODY
    )

    assert result["exit_code"] == platform_cli.EXIT_CLI_FAILED
    assert any("glab failed" in n for n in result["notes"])


def test_a_missing_cli_points_at_the_manual_route(repo, monkeypatch):
    """The branch is already pushed by then, so this must not read as a hard failure."""
    _remote(repo, "https://gitlab.com/grp/proj.git")
    real_which = platform_cli.shutil.which
    monkeypatch.setattr(
        platform_cli.shutil, "which", lambda name: None if name == "glab" else real_which(name)
    )

    result = platform_cli.run(
        repo, "pr-create", base="main", head="feat", title="T", body_file="BODY.md", body=_BODY
    )

    assert result["exit_code"] == platform_cli.EXIT_CLI_FAILED
    assert any("manually" in n for n in result["notes"])


def test_dry_run_creates_nothing(repo, stub_cli):
    _remote(repo, "https://gitlab.com/grp/proj.git")
    stub_cli("glab")

    result = platform_cli.run(
        repo,
        "pr-create",
        base="main",
        head="feat",
        title="T",
        body_file="BODY.md",
        body=_BODY,
        dry_run=True,
    )

    assert result["exit_code"] == platform_cli.EXIT_OK
    assert result["command"][0] == "glab"
    assert not stub_cli.log.exists(), "dry run invoked the CLI"


def test_output_without_a_url_is_not_an_error(repo, stub_cli):
    """Some CLI versions print nothing useful; the request was still created."""
    _remote(repo, "https://github.com/acme/widget.git")
    stub_cli("gh", url="created (no url printed)")

    result = platform_cli.run(
        repo, "pr-create", base="main", head="feat", title="T", body_file="BODY.md", body=_BODY
    )

    assert result["exit_code"] == platform_cli.EXIT_OK
    assert result["url"] is None


# --- resolve_body -------------------------------------------------------------


def test_resolve_body_reads_a_repo_relative_path(repo):
    assert platform_cli.resolve_body(repo, "BODY.md") == "## Summary\n\nbody\n"


def test_resolve_body_falls_back_to_a_path_outside_the_repo(repo, tmp_path):
    outside = tmp_path / "elsewhere.md"
    outside.write_text("scratchpad body\n")
    assert platform_cli.resolve_body(repo, str(outside)) == "scratchpad body\n"


@pytest.mark.parametrize("value", [None, "", "missing.md"])
def test_resolve_body_returns_none_when_there_is_nothing_to_read(repo, value):
    assert platform_cli.resolve_body(repo, value) is None


# --- main() / CLI -------------------------------------------------------------


def test_main_dry_run_renders_the_gitlab_command(repo, capsys):
    _remote(repo, "https://gitlab.com/grp/proj.git")
    rc = platform_cli.main(
        ["pr-create", "--base", "main", "--head", "feat", "--title", "T",
         "--body-file", "BODY.md", "--target-dir", str(repo), "--dry-run"]
    )  # fmt: skip
    assert rc == platform_cli.EXIT_OK
    out = capsys.readouterr().out
    assert "platform gitlab" in out
    assert "glab mr create --target-branch main --source-branch feat" in out


def test_main_json_output(repo, capsys):
    _remote(repo, "https://github.com/acme/widget.git")
    rc = platform_cli.main(
        ["pr-create", "--base", "main", "--head", "feat", "--title", "T",
         "--body-file", "BODY.md", "--target-dir", str(repo), "--dry-run", "--json"]
    )  # fmt: skip
    assert rc == platform_cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["platform"] == "github"
    assert payload["command"][:3] == ["gh", "pr", "create"]


def test_main_reports_an_undetectable_platform(repo, capsys):
    rc = platform_cli.main(
        ["pr-create", "--base", "main", "--head", "feat", "--body-file", "BODY.md",
         "--target-dir", str(repo), "--dry-run"]
    )  # fmt: skip
    assert rc == platform_cli.EXIT_USAGE
    assert "no `origin` remote" in capsys.readouterr().err


def test_main_requires_the_body_file_to_exist(repo, capsys):
    _remote(repo, "https://github.com/acme/widget.git")
    rc = platform_cli.main(
        ["pr-create", "--base", "main", "--head", "feat", "--body-file", "missing.md",
         "--target-dir", str(repo)]
    )  # fmt: skip
    assert rc == platform_cli.EXIT_USAGE
    assert "--body-file is required" in capsys.readouterr().err


def test_main_reports_an_unsupported_action(repo, capsys):
    _remote(repo, "https://gitlab.com/grp/proj.git")
    rc = platform_cli.main(["release-create", "--tag", "v1.0.0", "--target-dir", str(repo)])
    assert rc == platform_cli.EXIT_USAGE
    assert "--generate-notes" in capsys.readouterr().err


def test_main_prints_repo_view_data(repo, stub_cli, capsys):
    _remote(repo, "https://github.com/acme/widget.git")
    stub_cli("gh", stdout='echo \'{"defaultBranchRef":{"name":"trunk"},"visibility":"PRIVATE"}\'')

    rc = platform_cli.main(["repo-view", "--target-dir", str(repo)])

    assert rc == platform_cli.EXIT_OK
    out = capsys.readouterr().out
    assert "trunk" in out and "private" in out


def test_main_executes_when_not_a_dry_run(repo, stub_cli, capsys):
    _remote(repo, "https://gitlab.com/grp/proj.git")
    stub_cli("glab", url="https://gitlab.com/grp/proj/-/merge_requests/9")
    rc = platform_cli.main(
        ["pr-create", "--base", "main", "--head", "feat", "--title", "T",
         "--body-file", "BODY.md", "--target-dir", str(repo)]
    )  # fmt: skip
    assert rc == platform_cli.EXIT_OK
    assert "merge_requests/9" in capsys.readouterr().out
