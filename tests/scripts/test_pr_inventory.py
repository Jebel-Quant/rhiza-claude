"""Tests for the request inventory (`scripts/pr_inventory.py`).

The payloads are trimmed copies of real answers: the GitHub one from `gh pr list --json`
against this repo, the GitLab one in the shape `glab mr list --output json` prints. What
matters most is the direction of the failure modes — an unreadable issue must not read as
closed, and a missing `has_conflicts` must not read as mergeable — because each of those
would make a request look obsolete or ready when it is neither.

The flags are checked against the real CLIs' `--help`, for the reason
`test_platform_cli.py` records: stubbing a CLI and asserting the argv proves only that the
code agrees with itself.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pr_inventory
import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")

NOW = datetime(2026, 10, 9, tzinfo=UTC)

_GH_PR = {
    "number": 271,
    "title": "chore: relicense",
    "url": "https://github.com/acme/widget/pull/271",
    "headRefName": "chore/license",
    "baseRefName": "main",
    "isDraft": False,
    "author": {"login": "tschm"},
    "createdAt": "2026-10-01T07:45:24Z",
    "updatedAt": "2026-10-08T09:58:46Z",
    "mergeable": "MERGEABLE",
    "files": [
        {"path": "LICENSE", "additions": 85, "deletions": 21, "changeType": "MODIFIED"},
        {"path": "README.md", "additions": 17, "deletions": 1, "changeType": "MODIFIED"},
    ],
    "closingIssuesReferences": [{"number": 7}],
    "labels": [{"name": "chore"}],
}

_GL_MR = {
    "iid": 12,
    "title": "feat: thing",
    "web_url": "https://gitlab.com/grp/proj/-/merge_requests/12",
    "source_branch": "feat",
    "target_branch": "main",
    "draft": True,
    "author": {"username": "tschm"},
    "created_at": "2026-09-01T00:00:00.000Z",
    "updated_at": "2026-10-02T00:00:00.000Z",
    "has_conflicts": True,
    "labels": ["feature"],
    "description": "Closes #3 and mentions #4.",
}

_DIFF = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n+x\n-y\n"


def _git(repo: Path, *args: str) -> None:
    """Run a git command, raising with output on failure."""
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)}:\n{result.stderr}"


def _repo(tmp_path: Path, url: str) -> Path:
    """A git repo whose `origin` is *url*."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "remote", "add", "origin", url)
    return repo


@pytest.fixture
def github(tmp_path: Path) -> Path:
    """A repo on GitHub."""
    return _repo(tmp_path, "https://github.com/acme/widget.git")


@pytest.fixture
def gitlab(tmp_path: Path) -> Path:
    """A repo on GitLab."""
    return _repo(tmp_path, "https://gitlab.com/grp/proj.git")


@pytest.fixture
def stub(stub_cli_installer):
    """Install a CLI stub answering by subcommand: *answers* maps a verb to stdout.

    The verb is the second argv word (`list`, `view`, `diff`); an answer of ``None``
    makes that call exit 1, which is how a missing or invisible issue arrives.
    """

    def install(name: str, answers: dict[str, str | None]) -> None:
        stub_cli_installer(
            name,
            "import sys\n"
            f"answers = {answers!r}\n"
            "answer = answers.get(sys.argv[2])\n"
            "if answer is None:\n"
            "    sys.stderr.write('not found\\n')\n"
            "    sys.exit(1)\n"
            "print(answer)\n",
        )

    return install


class TestInventoryError:
    """The error raised when a platform CLI cannot answer."""

    def test_is_exception_with_message(self):
        err = pr_inventory.InventoryError("boom")
        assert isinstance(err, Exception)
        assert str(err) == "boom"


# --- argv ---------------------------------------------------------------------


def test_the_github_listing_asks_for_every_field_in_one_call():
    argv = pr_inventory.build_list_command("github", limit=7)
    assert argv[:5] == ["gh", "pr", "list", "--state", "open"]
    fields = argv[argv.index("--json") + 1].split(",")
    assert {"files", "mergeable", "closingIssuesReferences"} <= set(fields)
    assert argv[-2:] == ["--limit", "7"]


def test_the_gitlab_issue_state_is_read_as_json():
    assert pr_inventory.build_issue_state_command("gitlab", 3) == [
        "glab", "issue", "view", "3", "--output", "json",
    ]  # fmt: skip


def _long_flags_in_help(binary: str, subcommand: list[str]) -> set[str]:
    """Return the long flags `<binary> <subcommand> --help` documents."""
    result = subprocess.run(
        [binary, *subcommand, "--help"], capture_output=True, text=True, check=False
    )
    return set(re.findall(r"--[a-z][a-z0-9-]+", result.stdout + result.stderr))


@pytest.mark.parametrize(
    "argv",
    [
        pr_inventory.build_list_command("github", limit=5),
        pr_inventory.build_list_command("gitlab", limit=5),
        pr_inventory.build_diff_command(12),
        pr_inventory.build_issue_state_command("github", 3),
        pr_inventory.build_issue_state_command("gitlab", 3),
    ],
    ids=["gh-list", "glab-list", "glab-diff", "gh-issue", "glab-issue"],
)
def test_every_long_flag_exists_in_the_real_cli(argv):
    """The flags come back out of the CLI's own help text, not out of this module."""
    if shutil.which(argv[0]) is None:
        pytest.skip(f"{argv[0]} not installed")
    documented = _long_flags_in_help(argv[0], argv[1:3])
    used = {a for a in argv if a.startswith("--")}
    assert used <= documented, f"{' '.join(argv[:3])}: {sorted(used - documented)}"


# --- normalisation ------------------------------------------------------------


def test_a_github_request_is_normalised():
    request = pr_inventory.normalize_github(_GH_PR)

    assert request["id"] == 271
    assert request["branch"] == "chore/license" and request["base"] == "main"
    assert request["mergeable"] == "clean"
    assert request["author"] == "tschm"
    assert request["labels"] == ["chore"]
    assert [f["path"] for f in request["files"]] == ["LICENSE", "README.md"]
    assert request["closes"] == [7] and request["closes_source"] == "forge"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("CONFLICTING", "conflicting"), ("UNKNOWN", "unknown"), (None, "unknown")],
)
def test_github_mergeability_never_defaults_to_clean(raw, expected):
    assert pr_inventory.normalize_github({**_GH_PR, "mergeable": raw})["mergeable"] == expected


def test_a_gitlab_request_is_normalised():
    files = pr_inventory.parse_diff(_DIFF)
    request = pr_inventory.normalize_gitlab(_GL_MR, files)

    assert request["id"] == 12
    assert request["branch"] == "feat" and request["base"] == "main"
    assert request["draft"] is True
    assert request["mergeable"] == "conflicting"
    assert request["files"] == [{"path": "README.md", "additions": 1, "deletions": 1}]
    assert request["closes"] == [3], "a bare mention is not a closing reference"
    assert request["closes_source"] == "description"


@pytest.mark.parametrize(("raw", "expected"), [(False, "clean"), (None, "unknown")])
def test_gitlab_mergeability_is_unknown_when_absent(raw, expected):
    payload = {key: value for key, value in _GL_MR.items() if key != "has_conflicts"}
    if raw is not None:
        payload["has_conflicts"] = raw
    assert pr_inventory.normalize_gitlab(payload, [])["mergeable"] == expected


def test_a_diff_ignores_lines_before_the_first_header():
    assert pr_inventory.parse_diff("+stray\n" + _DIFF)[0]["additions"] == 1


def test_an_unparseable_timestamp_is_none_not_zero():
    assert pr_inventory.days_between("yesterday", NOW) is None


# --- running the CLI ----------------------------------------------------------


def test_a_missing_cli_is_reported(github, monkeypatch):
    monkeypatch.setattr(pr_inventory.shutil, "which", lambda _: None)
    with pytest.raises(pr_inventory.InventoryError, match="not installed"):
        pr_inventory.run_cli(["gh", "pr", "list"], github)


def test_a_failing_cli_is_reported_with_its_first_line(github, stub):
    stub("gh", {})
    with pytest.raises(pr_inventory.InventoryError, match="not found"):
        pr_inventory.run_cli(["gh", "pr", "list"], github)


def test_non_json_output_is_reported(github, stub):
    stub("gh", {"list": "not json"})
    with pytest.raises(pr_inventory.InventoryError, match="did not answer JSON"):
        pr_inventory.run_json(["gh", "pr", "list"], github)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [('{"state": "CLOSED"}', "closed"), ('{"state": "OPEN"}', "open"), (None, "unknown")],
)
def test_an_unreadable_issue_is_unknown_never_closed(github, stub, answer, expected):
    """A reference the token cannot see must not make a request look obsolete."""
    stub("gh", {"view": answer})
    assert pr_inventory.issue_state("github", 7, github) == expected


def test_gitlab_says_opened_for_open(gitlab, stub):
    stub("glab", {"view": '{"state": "opened"}'})
    assert pr_inventory.issue_state("gitlab", 3, gitlab) == "open"


# --- collect ------------------------------------------------------------------


def test_collect_on_github_finds_closed_references_and_overlaps(github, stub):
    second = {**_GH_PR, "number": 272, "closingIssuesReferences": [], "files": [_GH_PR["files"][1]]}
    stub("gh", {"list": json.dumps([_GH_PR, second]), "view": '{"state": "CLOSED"}'})

    report = pr_inventory.collect(github, limit=10, now=NOW)

    first = report["requests"][0]
    assert first["additions"] == 102 and first["deletions"] == 22
    assert first["age_days"] == 7 and first["idle_days"] == 0
    assert first["closes_closed"] == [7]
    assert report["overlaps"] == [{"a": 271, "b": 272, "files": ["README.md"]}]


def test_collect_on_gitlab_reads_each_diff(gitlab, stub):
    stub("glab", {"list": json.dumps([_GL_MR]), "diff": _DIFF, "view": '{"state": "opened"}'})

    report = pr_inventory.collect(gitlab, limit=10, now=NOW)

    (request,) = report["requests"]
    assert request["files"][0]["path"] == "README.md"
    assert request["closes_closed"] == []
    assert request["idle_days"] == 7


def test_a_dry_run_asks_nothing(github):
    report = pr_inventory.collect(github, limit=3, dry_run=True)
    assert report["requests"] == [] and report["command"][0] == "gh"


# --- rendering and main -------------------------------------------------------


def test_render_shows_state_closes_and_overlaps():
    request = pr_inventory.normalize_gitlab(_GL_MR, pr_inventory.parse_diff(_DIFF))
    request.update(additions=1, deletions=1, age_days=38, idle_days=7, closes_closed=[3])
    report = {
        "platform": "gitlab",
        "command": ["glab", "mr", "list"],
        "requests": [request],
        "overlaps": [{"a": 12, "b": 13, "files": ["README.md"]}],
    }

    text = pr_inventory.render(report)

    assert "[conflicting, draft]" in text
    assert "closes #3  (already closed: #3)" in text
    assert "#12 & #13: README.md" in text


def test_render_closes_without_closed_ones_and_an_empty_listing():
    request = pr_inventory.normalize_github(_GH_PR)
    request.update(additions=0, deletions=0, age_days=1, idle_days=1, closes_closed=[])
    base = {"platform": "github", "command": ["gh"], "overlaps": []}

    assert "closes #7\n" in pr_inventory.render({**base, "requests": [request]}) + "\n"
    assert "no open requests" in pr_inventory.render({**base, "requests": []})


def test_main_prints_json(github, stub, capsys):
    stub("gh", {"list": "[]"})
    assert pr_inventory.main(["--target-dir", str(github), "--json"]) == pr_inventory.EXIT_OK
    assert json.loads(capsys.readouterr().out)["requests"] == []


def test_main_prints_text_for_a_dry_run(github, capsys):
    assert pr_inventory.main(["--target-dir", str(github), "--dry-run"]) == pr_inventory.EXIT_OK
    assert "no open requests" in capsys.readouterr().out


def test_main_reports_a_failed_cli(github, stub):
    stub("gh", {})
    assert pr_inventory.main(["--target-dir", str(github)]) == pr_inventory.EXIT_CLI_FAILED


def test_main_reports_an_unknown_platform(tmp_path):
    repo = _repo(tmp_path, "https://example.invalid/acme/widget.git")
    assert pr_inventory.main(["--target-dir", str(repo)]) == pr_inventory.EXIT_NO_PLATFORM


def test_requests_sharing_no_file_do_not_overlap():
    a = {"id": 1, "files": [{"path": "x"}]}
    b = {"id": 2, "files": [{"path": "y"}]}
    assert pr_inventory.overlaps([a, b]) == []


def test_render_omits_the_closes_line_when_there_is_nothing_to_close():
    request = pr_inventory.normalize_github({**_GH_PR, "closingIssuesReferences": []})
    request.update(additions=0, deletions=0, age_days=1, idle_days=1, closes_closed=[])
    report = {"platform": "github", "command": ["gh"], "overlaps": [], "requests": [request]}

    assert "closes" not in pr_inventory.render(report)
