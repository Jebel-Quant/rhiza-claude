"""Tests for the issue reader (`scripts/issue_status.py`).

Two kinds of test, and the split is deliberate.

Most of them stub the forge, because the normalisation this module exists for is a
pure function of a payload and a stub is the only way to hold both platforms' payloads
side by side. The risk in that is the one `platform_cli.py`'s docstring records having
shipped: asserting the argv a stub received proves the code agrees with **itself**, and
it agreed all the way through `glab mr create --description-file`, a flag `glab` has
never had.

So the second kind checks the argv against the real CLIs' own `--help` output, the way
`test_pr_status.py` does. Those skip when the binary is absent, which is the honest
trade: they cannot run everywhere, and where they do run they are the only tests that
can catch a flag nobody has.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import issue_status
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
    """A directory standing in for a checkout; the forge is stubbed, so it stays bare."""
    return tmp_path


def _stub(monkeypatch, answers):
    """Make `run_json` answer from *answers*, keyed by the subcommand pair."""

    def fake(command, target_dir):
        key = " ".join(command[:2])
        if key not in answers:
            raise issue_status.ForgeQueryError(f"no stub for {key}")
        value = answers[key]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(issue_status, "run_json", fake)


class TestForgeQueryError:
    """The error raised when a platform CLI could not be asked, or did not answer."""

    def test_is_exception_with_message(self):
        err = issue_status.ForgeQueryError("boom")
        assert isinstance(err, Exception)
        assert str(err) == "boom"


# --- argv ---------------------------------------------------------------------


def test_the_github_listing_asks_for_open_issues_as_json():
    argv = issue_status.build_issue_command("github", limit=5, labels=[])
    assert argv[:5] == ["gh", "issue", "list", "--state", "open"]
    assert "--limit" in argv and "5" in argv


def test_github_repeats_the_label_flag():
    argv = issue_status.build_issue_command("github", limit=5, labels=["a", "b"])
    assert argv.count("--label") == 2


def test_gitlab_joins_the_labels_with_commas():
    """The second place the two CLIs stop lining up, after the field names."""
    argv = issue_status.build_issue_command("gitlab", limit=5, labels=["a", "b"])
    assert argv[-2:] == ["--label", "a,b"]


def test_gitlab_omits_the_label_flag_entirely_when_there_are_none():
    assert "--label" not in issue_status.build_issue_command("gitlab", limit=5, labels=[])


def test_github_passes_the_state_through():
    argv = issue_status.build_issue_command("github", limit=5, labels=[], state="all")
    assert argv[3:5] == ["--state", "all"]


@pytest.mark.parametrize(
    ("state", "flags"), [("open", []), ("closed", ["--closed"]), ("all", ["--all"])]
)
def test_gitlab_spells_each_state_as_its_own_flag(state, flags):
    """`glab issue list` has no `--state`: open is the default, the rest are flags."""
    argv = issue_status.build_issue_command("gitlab", limit=5, labels=[], state=state)
    assert argv[7:] == flags


def test_the_request_listings_differ_by_more_than_the_binary():
    assert issue_status.build_request_command("github", limit=3)[:3] == ["gh", "pr", "list"]
    assert issue_status.build_request_command("gitlab", limit=3)[:3] == ["glab", "mr", "list"]


def test_github_offers_two_ways_to_resolve_a_reference():
    """One number may name an issue or a PR, and only trying tells you which."""
    commands = issue_status.build_reference_commands("github", 75)
    assert [c[1] for c in commands] == ["issue", "pr"]


def test_gitlab_offers_one_because_a_hash_is_always_an_issue():
    assert issue_status.build_reference_commands("gitlab", 75) == [
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
    "gh-issues": ("gh", lambda: issue_status.build_issue_command("github", limit=5, labels=["a"])),
    "glab-issues": (
        "glab",
        lambda: issue_status.build_issue_command("gitlab", limit=5, labels=["a"]),
    ),
    "gh-history": (
        "gh",
        lambda: issue_status.build_issue_command("github", limit=5, labels=[], state="all"),
    ),
    "glab-history": (
        "glab",
        lambda: issue_status.build_issue_command("gitlab", limit=5, labels=[], state="all"),
    ),
    "glab-closed": (
        "glab",
        lambda: issue_status.build_issue_command("gitlab", limit=5, labels=[], state="closed"),
    ),
    "gh-requests": ("gh", lambda: issue_status.build_request_command("github", limit=5)),
    "glab-requests": ("glab", lambda: issue_status.build_request_command("gitlab", limit=5)),
    "gh-ref-issue": ("gh", lambda: issue_status.build_reference_commands("github", 7)[0]),
    "gh-ref-pr": ("gh", lambda: issue_status.build_reference_commands("github", 7)[1]),
    "glab-ref": ("glab", lambda: issue_status.build_reference_commands("gitlab", 7)[0]),
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
    assert set(issue_status._GH_FIELDS.split(",")) <= offered
    assert set(issue_status._GH_REQUEST_FIELDS.split(",")) <= offered


# --- normalisation ------------------------------------------------------------


def test_both_platforms_land_on_the_same_object():
    """Five keys differ and not one of them errors when read with the wrong name."""
    assert issue_status.normalize("github", GH_ISSUE) == issue_status.normalize(
        "gitlab", GLAB_ISSUE
    )


def test_a_null_body_becomes_an_empty_string_not_none():
    """`gh` returns null for an issue filed with no description."""
    issue = issue_status.normalize("github", {"number": 1, "body": None})
    assert issue["body"] == ""


def test_a_missing_author_does_not_raise():
    assert issue_status.normalize("github", {"number": 1})["author"] == ""
    assert issue_status.normalize("gitlab", {"iid": 1})["author"] == ""


def test_github_labels_are_objects_and_gitlab_labels_are_strings():
    assert issue_status.normalize("github", GH_ISSUE)["labels"] == ["bug"]
    assert issue_status.normalize("gitlab", GLAB_ISSUE)["labels"] == ["bug"]


def test_both_platforms_spell_a_state_the_same_way_once_normalised():
    """GitHub says `OPEN`, GitLab `opened`; a caller comparing one would miss the other."""
    gh = issue_status.normalize("github", {**GH_ISSUE, "state": "OPEN"})
    lab = issue_status.normalize("gitlab", {**GLAB_ISSUE, "state": "opened"})
    assert gh["state"] == lab["state"] == "open"


def test_github_says_why_an_issue_was_closed():
    raw = {**GH_ISSUE, "state": "CLOSED", "stateReason": "NOT_PLANNED", "closedAt": "t"}
    issue = issue_status.normalize("github", raw)
    assert (issue["state"], issue["state_reason"], issue["closed"]) == (
        "closed",
        "not_planned",
        "t",
    )


def test_gitlab_records_no_reason_and_none_is_invented():
    raw = {**GLAB_ISSUE, "state": "closed", "closed_at": "t"}
    issue = issue_status.normalize("gitlab", raw)
    assert (issue["state"], issue["state_reason"], issue["closed"]) == ("closed", "", "t")


# --- run_json -----------------------------------------------------------------


def test_a_missing_binary_is_reported_not_guessed_around(repo, monkeypatch):
    monkeypatch.setattr(issue_status.shutil, "which", lambda _: None)
    with pytest.raises(issue_status.ForgeQueryError, match="not installed"):
        issue_status.run_json(["gh", "issue", "list"], repo)


def test_a_failing_cli_surfaces_its_first_line(repo):
    with pytest.raises(issue_status.ForgeQueryError):
        issue_status.run_json(["git", "rev-parse", "--not-a-flag"], repo)


def test_a_successful_call_parses_its_stdout(repo):
    assert issue_status.run_json(["echo", '{"a": 1}'], repo) == {"a": 1}


def test_empty_stdout_is_an_empty_list_not_a_parse_error(repo):
    """`gh issue list` prints nothing at all when a repo has no open issues."""
    assert issue_status.run_json(["true"], repo) == []


# --- the lock -----------------------------------------------------------------


def test_an_unmanaged_repo_owns_everything_in_it(repo):
    assert issue_status.managed_paths(repo) == set()


def test_a_managed_repo_reports_its_synced_paths(repo):
    (repo / ".rhiza").mkdir()
    (repo / ".rhiza" / "template.lock").write_text(
        "files:\n- pytest.ini\n- ruff.toml\n", encoding="utf-8"
    )
    assert issue_status.managed_paths(repo) == {"pytest.ini", "ruff.toml"}


# --- references ---------------------------------------------------------------


def test_a_reference_resolved_as_an_issue_stops_before_trying_the_pr(repo, monkeypatch):
    _stub(monkeypatch, {"gh issue": {"state": "CLOSED"}})
    assert issue_status.resolve_references("github", repo, [75]) == {75: "CLOSED"}


def test_a_reference_that_is_a_pr_falls_through_to_the_second_command(repo, monkeypatch):
    _stub(
        monkeypatch,
        {
            "gh issue": issue_status.ForgeQueryError("not an issue"),
            "gh pr": {"state": "MERGED"},
        },
    )
    assert issue_status.resolve_references("github", repo, [86]) == {86: "MERGED"}


def test_a_reference_nothing_can_answer_is_unresolved_rather_than_guessed(repo, monkeypatch):
    _stub(monkeypatch, {})
    assert issue_status.resolve_references("github", repo, [1]) == {1: "unresolved"}


def test_a_blank_state_does_not_count_as_resolved(repo, monkeypatch):
    _stub(monkeypatch, {"gh issue": {"state": "  "}, "gh pr": {"state": ""}})
    assert issue_status.resolve_references("github", repo, [1]) == {1: "unresolved"}


def test_nothing_is_fetched_when_there_are_no_dependencies(repo, monkeypatch):
    _stub(monkeypatch, {})
    assert issue_status.resolve_references("github", repo, []) == {}


# --- open requests ------------------------------------------------------------


def test_a_request_mentioning_the_issue_is_found():
    requests = [{"number": 3, "title": "fix: thing", "body": "Closes #95"}]
    assert issue_status._requests_by_issue(requests, 95) == [3]


def test_a_request_mentioning_a_different_issue_is_not():
    requests = [{"number": 3, "title": "fix", "body": "Closes #94"}]
    assert issue_status._requests_by_issue(requests, 95) == []


def test_a_gitlab_request_is_found_by_its_iid():
    requests = [{"iid": 7, "title": "Closes #95", "body": None}]
    assert issue_status._requests_by_issue(requests, 95) == [7]


def test_a_request_with_no_number_at_all_is_dropped():
    assert issue_status._requests_by_issue([{"title": "Closes #95"}], 95) == []


# --- collect ------------------------------------------------------------------


def _collect(repo, monkeypatch, issues, requests=(), **kwargs):
    """Run `collect` against stubbed listings on a github remote."""
    monkeypatch.setattr(issue_status, "detect_platform", lambda _: "github")
    _stub(monkeypatch, {"gh issue": list(issues), "gh pr": list(requests)})
    return issue_status.collect(
        repo, limit=20, labels=[], only=kwargs.get("only", []), dry_run=False
    )


def test_a_dry_run_renders_the_argv_and_asks_the_forge_nothing(repo, monkeypatch):
    monkeypatch.setattr(issue_status, "detect_platform", lambda _: "github")
    monkeypatch.setattr(
        issue_status,
        "run_json",
        lambda *_: pytest.fail("a dry run must not reach the forge"),
    )
    report = issue_status.collect(repo, limit=20, labels=[], only=[], dry_run=True)
    assert report["dry_run"] and report["issues"] == []


def test_a_mechanical_issue_comes_back_mechanical(repo, monkeypatch):
    report = _collect(repo, monkeypatch, [GH_ISSUE])
    assert report["issues"][0]["signals"]["category"] == "mechanical"


def test_an_issue_with_an_open_request_is_blocked(repo, monkeypatch):
    requests = [{"number": 3, "title": "fix", "body": "Closes #95"}]
    report = _collect(repo, monkeypatch, [GH_ISSUE], requests)
    assert report["issues"][0]["signals"]["category"] == "blocked"


def test_only_narrows_to_the_issues_asked_for(repo, monkeypatch):
    other = {**GH_ISSUE, "number": 94}
    report = _collect(repo, monkeypatch, [GH_ISSUE, other], only=[94])
    assert [i["id"] for i in report["issues"]] == [94]


def test_a_closed_issue_is_listed_but_not_triaged(repo, monkeypatch):
    """Triage asks whether an issue can be fixed, which a closed one no longer asks."""
    closed = {**GH_ISSUE, "number": 90, "state": "CLOSED", "stateReason": "COMPLETED"}
    monkeypatch.setattr(issue_status, "detect_platform", lambda _: "github")
    _stub(monkeypatch, {"gh issue": [GH_ISSUE, closed], "gh pr": []})
    report = issue_status.collect(repo, limit=20, labels=[], only=[], dry_run=False, state="all")
    by_id = {i["id"]: i for i in report["issues"]}
    assert by_id[90]["signals"] is None
    assert by_id[95]["signals"]["category"] == "mechanical"
    assert report["state"] == "all"


def test_a_template_owned_mention_becomes_a_caution_not_a_category(repo, monkeypatch):
    (repo / ".rhiza").mkdir()
    (repo / ".rhiza" / "template.lock").write_text("files:\n- pytest.ini\n", encoding="utf-8")
    # On disk as well as in the lock, which is what a synced file actually looks like —
    # otherwise the absent-path caution fires too and this asserts the wrong thing.
    (repo / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    issue = {**GH_ISSUE, "body": "**done when…** it works, unlike `pytest.ini`."}
    report = _collect(repo, monkeypatch, [issue])
    assert report["issues"][0]["signals"]["category"] == "mechanical"
    assert report["issues"][0]["signals"]["cautions"] == [
        "mentions template-owned paths: pytest.ini"
    ]


def test_a_path_that_resolves_raises_no_caution(repo, monkeypatch):
    (repo / "real.toml").write_text("", encoding="utf-8")
    issue = {**GH_ISSUE, "body": "**done when…** `real.toml` is fixed."}
    report = _collect(repo, monkeypatch, [issue])
    assert report["issues"][0]["signals"]["cautions"] == []


def test_a_settled_dependency_makes_an_issue_stale(repo, monkeypatch):
    monkeypatch.setattr(issue_status, "detect_platform", lambda _: "github")
    _stub(
        monkeypatch,
        {
            "gh issue": [{**GH_ISSUE, "body": "**Sequencing:** after #75."}],
            "gh pr": [],
        },
    )
    monkeypatch.setattr(issue_status, "resolve_references", lambda *_: {75: "MERGED"})
    report = issue_status.collect(repo, limit=20, labels=[], only=[], dry_run=False)
    assert report["issues"][0]["signals"]["category"] == "stale"
    assert report["issues"][0]["reference_states"] == {"75": "MERGED"}


def test_gitlab_says_out_loud_what_it_cannot_resolve(repo, monkeypatch):
    monkeypatch.setattr(issue_status, "detect_platform", lambda _: "gitlab")
    _stub(monkeypatch, {"glab issue": [GLAB_ISSUE], "glab mr": []})
    report = issue_status.collect(repo, limit=20, labels=[], only=[], dry_run=False)
    assert any("unresolved" in note for note in report["notes"])


def test_github_has_no_such_note(repo, monkeypatch):
    assert _collect(repo, monkeypatch, [GH_ISSUE])["notes"] == []


# --- rendering ----------------------------------------------------------------


def test_a_dry_run_renders_as_the_command_line():
    rendered = issue_status.render({"dry_run": True, "command": ["gh", "issue", "list"]})
    assert rendered == "gh issue list"


def test_an_empty_tracker_says_so():
    report = {"dry_run": False, "platform": "github", "issues": [], "notes": []}
    assert "no open issues" in issue_status.render(report)


def test_an_empty_history_does_not_claim_to_be_about_open_issues():
    report = {"dry_run": False, "platform": "github", "issues": [], "state": "all"}
    assert issue_status.render(report).endswith("no issues")


def test_a_closed_issue_renders_with_its_reason_or_says_there_is_none():
    closed = {"id": 90, "title": "t", "signals": None, "state_reason": "not_planned"}
    silent = {"id": 91, "title": "u", "signals": None, "state_reason": ""}
    report = {"dry_run": False, "platform": "github", "issues": [closed, silent]}
    rendered = issue_status.render(report)
    assert "#90" in rendered and "not_planned" in rendered
    assert "reason unrecorded" in rendered


def test_the_render_names_the_category_and_the_reason(repo, monkeypatch):
    rendered = issue_status.render(_collect(repo, monkeypatch, [GH_ISSUE]))
    assert "mechanical" in rendered
    assert "acceptance criterion, single-valued" in rendered


def test_a_note_is_rendered(repo, monkeypatch):
    monkeypatch.setattr(issue_status, "detect_platform", lambda _: "gitlab")
    _stub(monkeypatch, {"glab issue": [], "glab mr": []})
    report = issue_status.collect(repo, limit=20, labels=[], only=[], dry_run=False)
    assert "note" in issue_status.render(report)


def test_a_caution_is_rendered(repo, monkeypatch):
    issue = {**GH_ISSUE, "body": "**done when…** `gone.toml` is fixed."}
    rendered = issue_status.render(_collect(repo, monkeypatch, [issue]))
    assert "caution: names paths that do not resolve: gone.toml" in rendered


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        ({"category": "blocked", "open_requests": [3]}, "already has an open request"),
        ({"category": "stale", "superseded_by": [75]}, "sequenced behind"),
        ({"category": "decision", "acceptance": None}, "no acceptance criterion"),
        (
            {"category": "decision", "acceptance": "x", "decide_markers": ["pick one"]},
            "hands the reader a choice",
        ),
        ({"category": "optional"}, "more than one outcome"),
        ({"category": "mechanical"}, "single-valued"),
    ],
)
def test_every_category_explains_itself(facts, expected):
    assert expected in issue_status._why(facts)


# --- main ---------------------------------------------------------------------


def test_an_undeterminable_platform_exits_two(repo, capsys):
    code = issue_status.main(["--target-dir", str(repo)])
    assert code == issue_status.EXIT_NO_PLATFORM
    assert "ERROR" in capsys.readouterr().err


def test_a_failing_cli_exits_one(repo, monkeypatch, capsys):
    monkeypatch.setattr(issue_status, "detect_platform", lambda _: "github")
    _stub(monkeypatch, {})
    code = issue_status.main(["--target-dir", str(repo)])
    assert code == issue_status.EXIT_CLI_FAILED
    assert "ERROR" in capsys.readouterr().err


def test_a_dry_run_exits_zero_and_prints_the_argv(repo, monkeypatch, capsys):
    monkeypatch.setattr(issue_status, "detect_platform", lambda _: "github")
    code = issue_status.main(["--target-dir", str(repo), "--dry-run"])
    assert code == issue_status.EXIT_OK
    assert capsys.readouterr().out.startswith("gh issue list")


def test_json_output_is_parseable(repo, monkeypatch, capsys):
    monkeypatch.setattr(issue_status, "detect_platform", lambda _: "github")
    _stub(monkeypatch, {"gh issue": [GH_ISSUE], "gh pr": []})
    code = issue_status.main(["--target-dir", str(repo), "--json"])
    assert code == issue_status.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["issues"][0]["signals"]["category"] == "mechanical"


def test_the_state_flag_reaches_the_listing(repo, monkeypatch, capsys):
    monkeypatch.setattr(issue_status, "detect_platform", lambda _: "github")
    code = issue_status.main(["--target-dir", str(repo), "--dry-run", "--state", "closed"])
    assert code == issue_status.EXIT_OK
    assert "--state closed" in capsys.readouterr().out


def test_an_empty_tracker_is_success_not_failure(repo, monkeypatch, capsys):
    """Nothing to fix is an answer, not an error — the exit code has to say so."""
    monkeypatch.setattr(issue_status, "detect_platform", lambda _: "github")
    _stub(monkeypatch, {"gh issue": [], "gh pr": []})
    assert issue_status.main(["--target-dir", str(repo)]) == issue_status.EXIT_OK
    assert "no open issues" in capsys.readouterr().out
