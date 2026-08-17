"""Tests for the CI-state reader (`scripts/pr_status.py`).

Three things are worth asserting here, and only the first is obvious.

**The normalisation.** Two CLIs, three payload shapes, six state names. The payloads
below are trimmed copies of real answers — the GitHub ones from `gh pr view --json
statusCheckRollup` against this repo, which is why they carry both `__typename`s: a
GitHub Actions job and an external service posting a commit status arrive in the same
array and share almost no keys.

**The direction of the rollup.** Every mistake here fails the same way — a request that
is not green reads as green, and gets merged. So the tests are written from that side:
one failing job outweighs ten passing ones, a still-running job is not a pass, and *no
checks at all* is not a pass either.

**The flags, against the real CLIs.** `test_every_long_flag_exists_in_the_real_cli` in
`test_platform_cli.py` exists because a `glab` flag that had never existed shipped and
the self-consistent tests passed anyway. The same check runs here, over the same CLIs,
for the same reason: this module's argv is no more checkable by inspection than that
one's was.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pr_status
import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _git(repo: Path, *args: str) -> None:
    """Run a git command, raising with output on failure."""
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)}:\n{result.stderr}"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo whose `origin` is on GitHub."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "remote", "add", "origin", "https://github.com/acme/widget.git")
    return tmp_path


@pytest.fixture
def gitlab_repo(tmp_path: Path) -> Path:
    """A git repo whose `origin` is on GitLab."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "remote", "add", "origin", "https://gitlab.com/grp/proj.git")
    return tmp_path


@pytest.fixture
def stub_cli(tmp_path: Path, stub_cli_installer):
    """Put a fake `gh`/`glab` on PATH that records its argv and prints canned stdout.

    Answers are keyed by a substring of the argv, so one stub can serve the two calls
    the GitLab path makes (list the requests, then get each one's pipeline). The stub is
    Python rather than bash so it runs on Windows too — see `stub_cli_installer` in
    `tests/conftest.py` for why the delivery differs by platform.
    """
    log = tmp_path / "invocations.txt"

    def install(name: str, answers: dict[str, str], *, exit_code: int = 0) -> None:
        payloads: dict[str, str] = {}
        for index, (key, value) in enumerate(answers.items()):
            payload = tmp_path / f"{name}-{index}.out"
            payload.write_text(value, encoding="utf-8")
            payloads[key] = str(payload)
        stub_cli_installer(
            name,
            "import sys\n"
            f"argv = ' '.join(sys.argv[1:])\n"
            f"with open({str(log)!r}, 'a', encoding='utf-8') as fh:\n"
            f"    fh.write({name!r} + ' ' + argv + '\\n')\n"
            f"for key, path in {payloads!r}.items():\n"
            "    if key in argv:\n"
            "        with open(path, encoding='utf-8') as fh:\n"
            "            sys.stdout.write(fh.read())\n"
            f"        sys.exit({exit_code})\n"
            "sys.stdout.write('null')\n"
            f"sys.exit({exit_code})\n",
        )

    install.log = log  # type: ignore[attr-defined]
    return install


# Real shapes, trimmed. Both `__typename`s, because both arrive in the same array.
_CHECK_RUN = {
    "__typename": "CheckRun",
    "name": "tests",
    "workflowName": "CI",
    "status": "COMPLETED",
    "conclusion": "FAILURE",
    "detailsUrl": "https://github.com/acme/widget/actions/runs/12345/job/67890",
}
_STATUS_CONTEXT = {
    "__typename": "StatusContext",
    "context": "CodeFactor",
    "state": "SUCCESS",
    "targetUrl": "https://www.codefactor.io/repository/github/acme/widget/pull/7",
}


def _pr(*checks: dict) -> dict:
    """One `gh pr list` entry carrying *checks*."""
    return {
        "number": 7,
        "title": "fix the thing",
        "headRefName": "fix/thing",
        "url": "https://github.com/acme/widget/pull/7",
        "isDraft": False,
        "statusCheckRollup": list(checks),
    }


class TestForgeQueryError:
    """The error raised when a platform CLI cannot be reached or read."""

    def test_is_exception_with_message(self):
        err = pr_status.ForgeQueryError("boom")
        assert isinstance(err, Exception)
        assert str(err) == "boom"


# --- the argv, both platforms -------------------------------------------------


def test_the_github_query_asks_for_the_rollup():
    argv = pr_status.build_list_command("github", branch=None, limit=5)
    assert argv[:4] == ["gh", "pr", "list", "--state"]
    assert "statusCheckRollup" in argv[argv.index("--json") + 1]
    assert "--head" not in argv, "no branch was asked for"


def test_the_github_query_narrows_to_a_branch():
    argv = pr_status.build_list_command("github", branch="fix/thing", limit=5)
    assert argv[-2:] == ["--head", "fix/thing"]


def test_the_gitlab_query_uses_its_own_flag_names():
    """`--head` and `--limit` are gh's spellings; glab has neither."""
    argv = pr_status.build_list_command("gitlab", branch="fix/thing", limit=5)
    assert argv[:3] == ["glab", "mr", "list"]
    assert "--source-branch" in argv and "--head" not in argv
    assert "--per-page" in argv and "--limit" not in argv


def test_the_gitlab_query_without_a_branch_lists_everything():
    argv = pr_status.build_list_command("gitlab", branch=None, limit=5)
    assert "--source-branch" not in argv


def test_the_pipeline_is_fetched_by_merge_request_not_by_branch():
    """A detached MR pipeline is not the latest pipeline on the source branch."""
    argv = pr_status.build_pipeline_command(42)
    assert argv[:3] == ["glab", "ci", "get"]
    assert "--merge-request" in argv and "--branch" not in argv


def test_the_logs_command_points_at_the_run_not_the_job():
    """`gh run view` takes a run id; the job id in the URL is not one."""
    check = pr_status.normalize_github_check(_CHECK_RUN)
    assert pr_status.build_logs_command("github", check) == [
        "gh", "run", "view", "12345", "--log-failed",
    ]  # fmt: skip


def test_an_external_status_has_no_log_command():
    """Its log lives on someone else's server; pretending otherwise sends you nowhere."""
    check = pr_status.normalize_github_check(_STATUS_CONTEXT)
    assert pr_status.build_logs_command("github", check) is None


def test_a_details_url_without_a_run_segment_yields_no_log_command():
    check = {"url": "https://github.com/acme/widget/actions/runs"}
    assert pr_status.build_logs_command("github", check) is None


def test_the_gitlab_log_command_opens_the_failing_jobs():
    check = pr_status.normalize_gitlab_pipeline({"id": 99, "status": "failed"})
    assert pr_status.build_logs_command("gitlab", check) == [
        "glab", "ci", "get", "--pipeline-id", "99", "--status", "failed", "--with-job-details",
    ]  # fmt: skip


def test_a_pipelineless_gitlab_check_has_no_log_command():
    assert pr_status.build_logs_command("gitlab", {"state": pr_status.UNKNOWN}) is None


# --- checked against the real CLIs, not against ourselves ---------------------


def _long_flags_in_help(binary: str, subcommand: list[str]) -> set[str]:
    """Return the long flags `<binary> <subcommand> --help` documents."""
    result = subprocess.run(
        [binary, *subcommand, "--help"], capture_output=True, text=True, check=False
    )
    return set(re.findall(r"--[a-z][a-z0-9-]+", result.stdout + result.stderr))


_EVERY_ARGV = {
    "gh-list": ("gh", lambda: pr_status.build_list_command("github", branch="b", limit=5)),
    "glab-list": ("glab", lambda: pr_status.build_list_command("gitlab", branch="b", limit=5)),
    "glab-pipeline": ("glab", lambda: pr_status.build_pipeline_command(42)),
    "gh-logs": (
        "gh",
        lambda: pr_status.build_logs_command(
            "github", pr_status.normalize_github_check(_CHECK_RUN)
        ),
    ),
    "glab-logs": (
        "glab",
        lambda: pr_status.build_logs_command(
            "gitlab", pr_status.normalize_gitlab_pipeline({"id": 99, "status": "failed"})
        ),
    ),
}


@pytest.mark.parametrize("case", sorted(_EVERY_ARGV))
def test_every_long_flag_exists_in_the_real_cli(case):
    """Verify our argv against `--help`, which is the check stubbing cannot make.

    Asserting the argv a stub received proves the code agrees with itself, and it did
    agree all the way through shipping `glab mr create --description-file`. Here the
    flags come back out of the CLI's own help text.
    """
    binary, build = _EVERY_ARGV[case]
    if shutil.which(binary) is None:
        pytest.skip(f"{binary} not installed")

    argv = build()
    subcommand = [a for a in argv[1:] if not a.startswith("-")][:2]
    documented = _long_flags_in_help(binary, subcommand)
    used = {a for a in argv if a.startswith("--")}
    assert used <= documented, (
        f"{' '.join(argv[:3])} uses flag(s) {sorted(used - documented)} that "
        f"`{binary} {' '.join(subcommand)} --help` does not document"
    )


def test_the_requested_gh_json_fields_are_ones_gh_offers():
    """`gh pr list --json` errors on an unknown field, mid-run, in front of a user."""
    if shutil.which("gh") is None:
        pytest.skip("gh not installed")
    result = subprocess.run(
        ["gh", "pr", "list", "--json"], capture_output=True, text=True, check=False
    )
    offered = set(re.findall(r"[a-zA-Z]+", result.stdout + result.stderr))
    assert set(pr_status._GH_FIELDS.split(",")) <= offered


# --- normalisation ------------------------------------------------------------


def test_a_failing_actions_job_is_named_with_its_workflow():
    """`tests` alone is ambiguous when three workflows each define one."""
    check = pr_status.normalize_github_check(_CHECK_RUN)
    assert check["name"] == "tests (CI)"
    assert check["state"] == pr_status.FAILURE
    assert check["raw"] == "FAILURE"


def test_a_commit_status_is_read_with_its_own_keys():
    """Reading it with a CheckRun's keys makes an external required check invisible."""
    check = pr_status.normalize_github_check(_STATUS_CONTEXT)
    assert check["name"] == "CodeFactor"
    assert check["state"] == pr_status.SUCCESS
    assert check["url"].startswith("https://www.codefactor.io/")


@pytest.mark.parametrize(
    ("conclusion", "expected"),
    [
        ("SUCCESS", pr_status.SUCCESS),
        ("NEUTRAL", pr_status.SUCCESS),
        ("SKIPPED", pr_status.SKIPPED),
        ("CANCELLED", pr_status.CANCELLED),
        ("TIMED_OUT", pr_status.FAILURE),
        ("ACTION_REQUIRED", pr_status.FAILURE),
        ("SOMETHING_NEW", pr_status.UNKNOWN),
    ],
)
def test_every_github_conclusion_maps_somewhere(conclusion, expected):
    entry = {**_CHECK_RUN, "conclusion": conclusion}
    assert pr_status.normalize_github_check(entry)["state"] == expected


def test_an_unfinished_job_is_pending_not_unknown():
    """An in-flight job has no conclusion at all — reading for one buries it."""
    entry = {**_CHECK_RUN, "status": "IN_PROGRESS", "conclusion": None}
    check = pr_status.normalize_github_check(entry)
    assert check["state"] == pr_status.PENDING
    assert check["raw"] == "IN_PROGRESS"


def test_a_nameless_check_is_still_reported():
    assert pr_status.normalize_github_check({"__typename": "CheckRun"})["name"] == "(unnamed check)"


def test_a_nameless_status_is_still_reported():
    check = pr_status.normalize_github_check({"__typename": "StatusContext"})
    assert check["name"] == "(unnamed status)"
    assert check["state"] == pr_status.UNKNOWN


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("success", pr_status.SUCCESS),
        ("failed", pr_status.FAILURE),
        ("running", pr_status.PENDING),
        ("manual", pr_status.PENDING),
        ("canceled", pr_status.CANCELLED),
        ("skipped", pr_status.SKIPPED),
        ("something_new", pr_status.UNKNOWN),
    ],
)
def test_every_gitlab_pipeline_status_maps_somewhere(status, expected):
    payload = {"id": 3, "status": status, "web_url": "https://gitlab.com/grp/proj/-/pipelines/3"}
    assert pr_status.normalize_gitlab_pipeline(payload)["state"] == expected


def test_a_pipeline_without_an_id_is_still_readable():
    assert pr_status.normalize_gitlab_pipeline({"status": "success"})["name"] == "pipeline"


# --- the rollup ---------------------------------------------------------------


def test_one_failure_outweighs_every_pass():
    checks = [{"state": pr_status.SUCCESS}] * 10 + [{"state": pr_status.FAILURE}]
    assert pr_status.rollup(checks) == pr_status.FAILURE


def test_a_running_job_is_not_a_pass():
    checks = [{"state": pr_status.SUCCESS}, {"state": pr_status.PENDING}]
    assert pr_status.rollup(checks) == pr_status.PENDING


def test_no_checks_at_all_is_not_a_pass():
    """A workflow that never triggered shows a clean list. That is the bug, not the pass."""
    assert pr_status.rollup([]) == pr_status.UNKNOWN


def test_an_all_skipped_request_reads_as_skipped():
    assert pr_status.rollup([{"state": pr_status.SKIPPED}]) == pr_status.SKIPPED


def test_a_cancelled_check_outranks_a_pass():
    checks = [{"state": pr_status.SUCCESS}, {"state": pr_status.CANCELLED}]
    assert pr_status.rollup(checks) == pr_status.CANCELLED


# --- collect(), with the CLI stubbed ------------------------------------------


def test_github_requests_are_collected_and_rolled_up(repo, stub_cli):
    stub_cli("gh", {"pr list": json.dumps([_pr(_CHECK_RUN, _STATUS_CONTEXT)])})

    summary = pr_status.collect(repo, branch=None, limit=10)

    assert summary["platform"] == "github"
    request = summary["requests"][0]
    assert request["id"] == 7
    assert request["branch"] == "fix/thing"
    assert request["state"] == pr_status.FAILURE
    assert request["checks"][0]["logs_command"][:3] == ["gh", "run", "view"]


def test_gitlab_takes_a_second_call_for_the_pipeline(gitlab_repo, stub_cli):
    stub_cli(
        "glab",
        {
            "mr list": json.dumps(
                [
                    {
                        "iid": 4,
                        "title": "fix the thing",
                        "source_branch": "fix/thing",
                        "web_url": "https://gitlab.com/grp/proj/-/merge_requests/4",
                        "draft": True,
                    }
                ]
            ),
            "ci get": json.dumps({"id": 88, "status": "failed", "web_url": "https://x.test/88"}),
        },
    )

    summary = pr_status.collect(gitlab_repo, branch=None, limit=10)

    request = summary["requests"][0]
    assert request["id"] == 4 and request["draft"] is True
    assert request["state"] == pr_status.FAILURE
    assert request["checks"][0]["name"] == "pipeline #88"
    invoked = stub_cli.log.read_text()
    assert "glab mr list" in invoked and "glab ci get" in invoked


def test_a_request_with_no_pipeline_does_not_sink_the_report(gitlab_repo, stub_cli):
    """One MR that has not run yet must not cost the caller every other MR's state."""
    stub_cli("glab", {"mr list": json.dumps([{"iid": 4, "title": "t", "source_branch": "b"}])})

    summary = pr_status.collect(gitlab_repo, branch=None, limit=10)

    assert summary["requests"][0]["state"] == pr_status.UNKNOWN
    assert summary["requests"][0]["checks"] == []


def test_an_unreadable_pipeline_costs_only_that_request(gitlab_repo, stub_cli):
    """The pipeline is a second call per MR, so its failure must stay local to one MR."""
    stub_cli(
        "glab",
        {
            "mr list": json.dumps([{"iid": 4, "title": "t", "source_branch": "b"}]),
            "ci get": "<html>502 Bad Gateway</html>",
        },
    )

    summary = pr_status.collect(gitlab_repo, branch=None, limit=10)

    assert summary["requests"][0]["state"] == pr_status.UNKNOWN


def test_a_dry_run_queries_nothing(repo, stub_cli):
    stub_cli("gh", {})
    summary = pr_status.collect(repo, branch="fix/thing", limit=10, dry_run=True)
    assert summary["requests"] == []
    assert not stub_cli.log.exists(), "dry run invoked the CLI"


def test_a_missing_cli_is_reported_not_guessed_around(repo, monkeypatch):
    real_which = pr_status.shutil.which
    monkeypatch.setattr(
        pr_status.shutil, "which", lambda name: None if name == "gh" else real_which(name)
    )
    with pytest.raises(pr_status.ForgeQueryError, match="not installed"):
        pr_status.collect(repo, branch=None, limit=10)


def test_a_failing_cli_is_reported_not_swallowed(repo, stub_cli):
    """Not logged in is the common case, and it must not read as "no open requests"."""
    stub_cli("gh", {"pr list": "[]"}, exit_code=1)
    with pytest.raises(pr_status.ForgeQueryError, match="failed"):
        pr_status.collect(repo, branch=None, limit=10)


def test_non_json_output_is_reported(repo, stub_cli):
    stub_cli("gh", {"pr list": "not json at all"})
    with pytest.raises(pr_status.ForgeQueryError, match="not JSON"):
        pr_status.collect(repo, branch=None, limit=10)


# --- rendering ----------------------------------------------------------------


def test_the_report_shows_the_drill_down_under_a_failing_check(repo, stub_cli):
    stub_cli("gh", {"pr list": json.dumps([_pr(_CHECK_RUN)])})
    text = pr_status.render(pr_status.collect(repo, branch=None, limit=10))
    assert "#7 FAIL" in text
    assert "✗ tests (CI)" in text
    assert "logs: gh run view 12345 --log-failed" in text


def test_a_checkless_request_says_so_rather_than_showing_nothing(repo, stub_cli):
    stub_cli("gh", {"pr list": json.dumps([_pr()])})
    text = pr_status.render(pr_status.collect(repo, branch=None, limit=10))
    assert "no checks reported" in text


def test_a_draft_is_marked(repo, stub_cli):
    stub_cli("gh", {"pr list": json.dumps([{**_pr(_STATUS_CONTEXT), "isDraft": True}])})
    assert "[draft]" in pr_status.render(pr_status.collect(repo, branch=None, limit=10))


def test_an_empty_result_says_nothing_is_waiting(repo, stub_cli):
    stub_cli("gh", {"pr list": "[]"})
    assert "no open requests" in pr_status.render(pr_status.collect(repo, branch=None, limit=10))


def test_a_dry_run_never_claims_there_are_no_requests(repo):
    """It did not look. Saying "nothing is waiting on CI" would be an invented answer."""
    text = pr_status.render(pr_status.collect(repo, branch=None, limit=10, dry_run=True))
    assert "no open requests" not in text
    assert "dry run" in text


# --- main() / CLI -------------------------------------------------------------


def test_main_defaults_to_the_branch_you_are_on(repo, capsys):
    rc = pr_status.main(["--target-dir", str(repo), "--dry-run"])
    assert rc == pr_status.EXIT_OK
    assert "--head main" in capsys.readouterr().out


def test_main_all_drops_the_branch_filter(repo, capsys):
    rc = pr_status.main(["--target-dir", str(repo), "--all", "--dry-run"])
    assert rc == pr_status.EXIT_OK
    assert "--head" not in capsys.readouterr().out


def test_main_json_output(repo, stub_cli, capsys):
    stub_cli("gh", {"pr list": json.dumps([_pr(_CHECK_RUN)])})
    rc = pr_status.main(["--target-dir", str(repo), "--branch", "fix/thing", "--json"])
    assert rc == pr_status.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["requests"][0]["state"] == pr_status.FAILURE


def test_main_reports_an_undetectable_platform(tmp_path, capsys):
    _git(tmp_path, "init", "-q", "-b", "main")
    rc = pr_status.main(["--target-dir", str(tmp_path)])
    assert rc == pr_status.EXIT_USAGE
    assert "no `origin` remote" in capsys.readouterr().err


def test_main_reports_a_cli_failure_with_its_own_exit_code(repo, stub_cli, capsys):
    stub_cli("gh", {"pr list": "[]"}, exit_code=1)
    rc = pr_status.main(["--target-dir", str(repo), "--all"])
    assert rc == pr_status.EXIT_CLI_FAILED
    assert "failed" in capsys.readouterr().err


def test_main_honours_the_limit(repo, capsys):
    rc = pr_status.main(["--target-dir", str(repo), "--all", "--limit", "3", "--dry-run"])
    assert rc == pr_status.EXIT_OK
    assert "--limit 3" in capsys.readouterr().out
