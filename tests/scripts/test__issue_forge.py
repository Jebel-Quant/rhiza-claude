"""Tests for the forge half of the issue reader (`scripts/_issue_forge.py`).

Two kinds of test, and the split is deliberate.

Most of them are pure: the normalisation this module exists for is a function of a
payload, and holding both platforms' payloads side by side is the point. The risk in
asserting argv is the one `platform_cli.py`'s docstring records having shipped: it proves
the code agrees with **itself**, and it agreed all the way through
`glab mr create --description-file`, a flag `glab` has never had.

So the second kind checks the argv against the real CLIs' own `--help` output, the way
`test_pr_status.py` does. Those skip when the binary is absent, which is the honest
trade: they cannot run everywhere, and where they do run they are the only tests that
can catch a flag nobody has.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import _issue_forge
import pytest

# --- payloads -----------------------------------------------------------------

GH_ISSUE = {
    "number": 95,
    "title": "Drop the dead table",
    "body": "**Subcategory:** x\n\n**done when…** `make test` runs without the warning.",
    "labels": [{"name": "bug"}],
    "author": {"login": "tschm"},
    "createdAt": "2026-09-22T10:29:18Z",
    "url": "https://github.com/acme/widget/issues/95",
}

GLAB_ISSUE = {
    "iid": 95,
    "title": "Drop the dead table",
    "description": "**Subcategory:** x\n\n**done when…** `make test` runs without the warning.",
    "labels": ["bug"],
    "author": {"username": "tschm"},
    "created_at": "2026-09-22T10:29:18Z",
    "web_url": "https://github.com/acme/widget/issues/95",
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A directory to run the CLI in; nothing reads its contents."""
    return tmp_path


class TestForgeQueryError:
    """The error raised when a platform CLI could not be asked, or did not answer."""

    def test_is_exception_with_message(self):
        err = _issue_forge.ForgeQueryError("boom")
        assert isinstance(err, Exception)
        assert str(err) == "boom"


# --- argv ---------------------------------------------------------------------


def test_the_github_listing_asks_for_open_issues_as_json():
    argv = _issue_forge.build_issue_command("github", limit=5, labels=[])
    assert argv[:5] == ["gh", "issue", "list", "--state", "open"]
    assert "--limit" in argv and "5" in argv


def test_github_repeats_the_label_flag():
    argv = _issue_forge.build_issue_command("github", limit=5, labels=["a", "b"])
    assert argv.count("--label") == 2


def test_gitlab_joins_the_labels_with_commas():
    """The second place the two CLIs stop lining up, after the field names."""
    argv = _issue_forge.build_issue_command("gitlab", limit=5, labels=["a", "b"])
    assert argv[-2:] == ["--label", "a,b"]


def test_gitlab_omits_the_label_flag_entirely_when_there_are_none():
    assert "--label" not in _issue_forge.build_issue_command("gitlab", limit=5, labels=[])


def test_github_passes_the_state_through():
    argv = _issue_forge.build_issue_command("github", limit=5, labels=[], state="all")
    assert argv[3:5] == ["--state", "all"]


@pytest.mark.parametrize(
    ("state", "flags"), [("open", []), ("closed", ["--closed"]), ("all", ["--all"])]
)
def test_gitlab_spells_each_state_as_its_own_flag(state, flags):
    """`glab issue list` has no `--state`: open is the default, the rest are flags."""
    argv = _issue_forge.build_issue_command("gitlab", limit=5, labels=[], state=state)
    assert argv[7:] == flags


def test_the_request_listings_differ_by_more_than_the_binary():
    assert _issue_forge.build_request_command("github", limit=3)[:3] == ["gh", "pr", "list"]
    assert _issue_forge.build_request_command("gitlab", limit=3)[:3] == ["glab", "mr", "list"]


def test_github_offers_two_ways_to_resolve_a_reference():
    """One number may name an issue or a PR, and only trying tells you which."""
    commands = _issue_forge.build_reference_commands("github", 75)
    assert [c[1] for c in commands] == ["issue", "pr"]


def test_gitlab_offers_one_because_a_hash_is_always_an_issue():
    assert _issue_forge.build_reference_commands("gitlab", 75) == [
        ["glab", "issue", "view", "75", "--output", "json"]
    ]


# --- checked against the real CLIs, not against ourselves ---------------------


def _long_flags_in_help(binary: str, subcommand: list[str]) -> set[str]:
    """Return the long flags `<binary> <subcommand> --help` documents."""
    result = subprocess.run(
        [binary, *subcommand, "--help"], capture_output=True, text=True, check=False
    )
    return set(re.findall(r"--[a-z][a-z0-9-]+", result.stdout + result.stderr))


_EVERY_ARGV = {
    "gh-issues": ("gh", lambda: _issue_forge.build_issue_command("github", limit=5, labels=["a"])),
    "glab-issues": (
        "glab",
        lambda: _issue_forge.build_issue_command("gitlab", limit=5, labels=["a"]),
    ),
    "gh-history": (
        "gh",
        lambda: _issue_forge.build_issue_command("github", limit=5, labels=[], state="all"),
    ),
    "glab-history": (
        "glab",
        lambda: _issue_forge.build_issue_command("gitlab", limit=5, labels=[], state="all"),
    ),
    "glab-closed": (
        "glab",
        lambda: _issue_forge.build_issue_command("gitlab", limit=5, labels=[], state="closed"),
    ),
    "gh-requests": ("gh", lambda: _issue_forge.build_request_command("github", limit=5)),
    "glab-requests": ("glab", lambda: _issue_forge.build_request_command("gitlab", limit=5)),
    "gh-ref-issue": ("gh", lambda: _issue_forge.build_reference_commands("github", 7)[0]),
    "gh-ref-pr": ("gh", lambda: _issue_forge.build_reference_commands("github", 7)[1]),
    "glab-ref": ("glab", lambda: _issue_forge.build_reference_commands("gitlab", 7)[0]),
}


@pytest.mark.parametrize("case", sorted(_EVERY_ARGV))
def test_every_long_flag_exists_in_the_real_cli(case):
    """Verify our argv against `--help`, which is the check stubbing cannot make."""
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
    """`gh issue list --json` errors on an unknown field, mid-run, in front of a user."""
    if shutil.which("gh") is None:
        pytest.skip("gh not installed")
    result = subprocess.run(
        ["gh", "issue", "list", "--json"], capture_output=True, text=True, check=False
    )
    offered = set(re.findall(r"[a-zA-Z]+", result.stdout + result.stderr))
    assert set(_issue_forge._GH_FIELDS.split(",")) <= offered
    assert set(_issue_forge._GH_REQUEST_FIELDS.split(",")) <= offered


# --- normalisation ------------------------------------------------------------


def test_both_platforms_land_on_the_same_object():
    """Five keys differ and not one of them errors when read with the wrong name."""
    assert _issue_forge.normalize("github", GH_ISSUE) == _issue_forge.normalize(
        "gitlab", GLAB_ISSUE
    )


def test_a_null_body_becomes_an_empty_string_not_none():
    """`gh` returns null for an issue filed with no description."""
    issue = _issue_forge.normalize("github", {"number": 1, "body": None})
    assert issue["body"] == ""


def test_a_missing_author_does_not_raise():
    assert _issue_forge.normalize("github", {"number": 1})["author"] == ""
    assert _issue_forge.normalize("gitlab", {"iid": 1})["author"] == ""


def test_github_labels_are_objects_and_gitlab_labels_are_strings():
    assert _issue_forge.normalize("github", GH_ISSUE)["labels"] == ["bug"]
    assert _issue_forge.normalize("gitlab", GLAB_ISSUE)["labels"] == ["bug"]


def test_both_platforms_spell_a_state_the_same_way_once_normalised():
    """GitHub says `OPEN`, GitLab `opened`; a caller comparing one would miss the other."""
    gh = _issue_forge.normalize("github", {**GH_ISSUE, "state": "OPEN"})
    lab = _issue_forge.normalize("gitlab", {**GLAB_ISSUE, "state": "opened"})
    assert gh["state"] == lab["state"] == "open"


def test_github_says_why_an_issue_was_closed():
    raw = {**GH_ISSUE, "state": "CLOSED", "stateReason": "NOT_PLANNED", "closedAt": "t"}
    issue = _issue_forge.normalize("github", raw)
    assert (issue["state"], issue["state_reason"], issue["closed"]) == (
        "closed",
        "not_planned",
        "t",
    )


def test_gitlab_records_no_reason_and_none_is_invented():
    raw = {**GLAB_ISSUE, "state": "closed", "closed_at": "t"}
    issue = _issue_forge.normalize("gitlab", raw)
    assert (issue["state"], issue["state_reason"], issue["closed"]) == ("closed", "", "t")


# --- run_json -----------------------------------------------------------------


def test_a_missing_binary_is_reported_not_guessed_around(repo, monkeypatch):
    monkeypatch.setattr(_issue_forge.shutil, "which", lambda _: None)
    with pytest.raises(_issue_forge.ForgeQueryError, match="not installed"):
        _issue_forge.run_json(["gh", "issue", "list"], repo)


def test_a_failing_cli_surfaces_its_first_line(repo):
    with pytest.raises(_issue_forge.ForgeQueryError):
        _issue_forge.run_json(["git", "rev-parse", "--not-a-flag"], repo)


def test_a_successful_call_parses_its_stdout(repo):
    assert _issue_forge.run_json(["echo", '{"a": 1}'], repo) == {"a": 1}


def test_empty_stdout_is_an_empty_list_not_a_parse_error(repo):
    """`gh issue list` prints nothing at all when a repo has no open issues."""
    assert _issue_forge.run_json(["true"], repo) == []
