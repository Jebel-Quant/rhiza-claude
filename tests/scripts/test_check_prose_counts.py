"""Tests for the prose-count checker (`scripts/check_prose_counts.py`).

Two failure modes matter more than the rest, and both are drawn from real drift this
repo shipped: a count that stops matching the tree (the paper's "nine user-facing
commands" against ten), and a marker left behind by a rewritten sentence, which would
otherwise turn the gate into decoration.

The third thing worth testing is what the gate must **not** do. Its whole design rests
on staying silent about unmarked prose, because English cannot tell "read by three
commands" from "ten slash commands" — so a test pins that silence, and the marker's
placement freedom (above the claim, or inline with it) that the silence pays for.
"""

from __future__ import annotations

from pathlib import Path

import _rhiza_layout as layout
import check_prose_counts as cpc
import pytest


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A tree holding two commands, one procedure and three workflows, and no prose."""
    for name in ("init", "update"):
        skill = tmp_path / layout.SKILLS_DIR / name
        skill.mkdir(parents=True)
        (skill / layout.SKILL_FILE).write_text("stub\n", encoding="utf-8")
    (tmp_path / layout.PROMPTS_DIR).mkdir(parents=True)
    (tmp_path / layout.PROMPTS_DIR / "pr-base.md").write_text("stub\n", encoding="utf-8")
    (tmp_path / cpc.WORKFLOWS_DIR).mkdir(parents=True)
    for name in ("ci.yml", "book.yml", "release.yaml"):
        (tmp_path / cpc.WORKFLOWS_DIR / name).write_text("on: push\n", encoding="utf-8")
    return tmp_path


def write(repo: Path, name: str, text: str) -> None:
    """Write *text* to *name* under *repo*, creating parents as needed."""
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- counting the tree --------------------------------------------------------


def test_tally_counts_commands_procedures_and_both_workflow_extensions(repo):
    assert cpc.tally(repo) == {"commands": 2, "procedures": 1, "workflows": 3}


def test_tally_of_an_empty_tree_is_zero_everywhere(tmp_path):
    assert cpc.tally(tmp_path) == {"commands": 0, "procedures": 0, "workflows": 0}


# --- reading a number ---------------------------------------------------------


@pytest.mark.parametrize(("token", "expected"), [("one", 1), ("twenty", 20), ("7", 7), ("0", 0)])
def test_parse_count_reads_words_and_digits(token, expected):
    assert cpc.parse_count(token) == expected


# --- finding the marker -------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "% rhiza-count: commands",
        "# rhiza-count: commands",
        "<!-- rhiza-count: commands -->",
        "    rhiza-count:commands",
    ],
)
def test_a_marker_is_read_in_any_comment_syntax(line):
    assert cpc.marked_subjects(line) == ["commands"]


def test_one_marker_may_name_several_subjects():
    assert cpc.marked_subjects("% rhiza-count: commands procedures") == ["commands", "procedures"]


def test_prose_that_merely_mentions_a_subject_is_not_a_marker():
    assert cpc.marked_subjects("the ten slash commands you invoke") == []


# --- reading the claim --------------------------------------------------------


def test_a_claim_is_found_for_the_subject_asked_about():
    text = "ten user-facing commands, eight internal procedures"
    assert cpc.claimed(text, "commands") == (10, 0)
    assert cpc.claimed(text, "procedures") == (8, 0)


def test_a_claim_may_be_split_across_a_line_break():
    assert cpc.claimed("a catalogue of the ten\nskills under skills/", "commands") == (10, 0)


def test_a_claim_reports_its_own_line_not_the_markers():
    assert cpc.claimed("marker\nfiller\ntwo commands", "commands") == (2, 2)


def test_markup_between_the_number_and_the_noun_does_not_hide_the_claim():
    assert cpc.claimed("holds eight **internal procedures** they", "procedures") == (8, 0)
    assert cpc.claimed(r"\textbf{slash commands}: ten of", "commands") is None
    assert cpc.claimed(r"the ten \textbf{slash commands}", "commands") == (10, 0)


def test_a_capitalised_number_opening_a_sentence_is_still_a_claim():
    assert cpc.claimed("Eight user-facing commands ship.", "commands") == (8, 0)


def test_the_nearest_noun_wins_rather_than_a_further_one():
    assert cpc.claimed("two commands, one procedures", "commands") == (2, 0)
    assert cpc.claimed("two commands, one procedures", "procedures") == (1, 0)


def test_digits_are_read_as_readily_as_words():
    assert cpc.claimed("all 12 workflows", "workflows") == (12, 0)


def test_a_noun_more_than_two_words_from_its_number_is_not_a_claim():
    assert cpc.claimed("ten of the very best commands", "commands") is None


def test_unmark_flattens_markup_to_spaces():
    assert cpc.unmark("a-b **c**") == "a b   c  "


# --- what the gate reads ------------------------------------------------------


def test_scanned_files_finds_prose_and_ignores_everything_else(repo):
    write(repo, "README.md", "x\n")
    write(repo, "Makefile", "x\n")
    write(repo, "paper/intro.tex", "x\n")
    write(repo, "docs/index.md", "x\n")
    write(repo, "docs/skills/init.md", "x\n")
    write(repo, "docs/reports/coverage.xml", "<x/>\n")
    write(repo, "plugin/scripts/thing.py", "x\n")
    found = {path.relative_to(repo).as_posix() for path in cpc.scanned_files(repo)}
    assert found == {
        "README.md",
        "Makefile",
        "paper/intro.tex",
        "docs/index.md",
        "docs/skills/init.md",
    }


def test_scanned_files_reports_each_file_once(repo):
    write(repo, "docs/index.md", "x\n")
    assert len(cpc.scanned_files(repo)) == len(set(cpc.scanned_files(repo)))


# --- the gate ------------------------------------------------------------------


def test_a_marked_claim_that_matches_the_tree_passes(repo):
    write(repo, "README.md", "<!-- rhiza-count: commands -->\nthe two slash commands you invoke\n")
    assert cpc.check_prose_counts(repo) == ([], 1)


def test_a_marked_claim_that_no_longer_matches_the_tree_fails(repo):
    write(repo, "paper/intro.tex", "% rhiza-count: commands\nEight user-facing commands ship.\n")
    violations, checked = cpc.check_prose_counts(repo)
    assert checked == 1
    assert violations == ["paper/intro.tex:2 claims 8 commands, but the tree holds 2"]


def test_a_marker_may_sit_inline_with_its_claim(repo):
    write(repo, "docs/x.md", "| skills | The two slash commands | <!-- rhiza-count: commands -->\n")
    assert cpc.check_prose_counts(repo) == ([], 1)


def test_a_marker_whose_sentence_was_rewritten_away_fails(repo):
    write(repo, "Makefile", "# rhiza-count: workflows\n# the CI configuration (zizmor).\n")
    violations, checked = cpc.check_prose_counts(repo)
    assert checked == 1
    assert violations == [
        "Makefile:1 marks `workflows` but no claim about workflows follows it within 3 line(s)"
    ]


def test_local_mk_is_scanned_beside_the_makefile(repo):
    """A shimmed repo's own targets live in `local.mk`, and so do the claims about them.

    rhiza's v1.4 `Makefile` is template-owned, so a repo moving its targets out of it also
    moves the counted comments. Scanning only `Makefile` would have let this repo's own
    "eight workflows" claim leave the gate without failing anything.
    """
    write(repo, "local.mk", "# rhiza-count: workflows\n# the nine workflows (zizmor).\n")
    violations, checked = cpc.check_prose_counts(repo)
    assert checked == 1
    assert violations == ["local.mk:2 claims 9 workflows, but the tree holds 3"]


def test_a_marker_naming_something_uncounted_fails_and_is_not_counted_as_checked(repo):
    write(repo, "README.md", "<!-- rhiza-count: sprockets -->\nthree sprockets\n")
    violations, checked = cpc.check_prose_counts(repo)
    assert checked == 0
    assert violations == [
        "README.md:1 marks `sprockets`, which is not a counted subject "
        "(commands, procedures, workflows)"
    ]


def test_a_claim_beyond_the_window_is_out_of_reach(repo):
    body = "% rhiza-count: commands\n" + "filler\n" * cpc.WINDOW + "two commands\n"
    write(repo, "paper/intro.tex", body)
    violations, _ = cpc.check_prose_counts(repo)
    assert "no claim about commands follows it" in violations[0]


def test_unmarked_prose_is_never_checked_however_wrong_its_numbers(repo):
    write(repo, "CLAUDE.md", "`pr-base` is read by three commands, and there are 99 workflows.\n")
    assert cpc.check_prose_counts(repo) == ([], 0)


def test_every_marked_subject_on_one_marker_is_checked(repo):
    write(
        repo,
        "paper/intro.tex",
        "% rhiza-count: commands procedures\ntwo commands, one procedures\n",
    )
    assert cpc.check_prose_counts(repo) == ([], 2)


def test_violations_from_several_files_are_all_reported(repo):
    write(repo, "README.md", "<!-- rhiza-count: commands -->\nnine commands\n")
    write(repo, "Makefile", "# rhiza-count: workflows\n# nine workflows\n")
    violations, checked = cpc.check_prose_counts(repo)
    assert checked == 2
    assert len(violations) == 2


# --- the CLI -------------------------------------------------------------------


def test_main_reports_success_and_the_number_of_claims(repo, monkeypatch, capsys):
    write(repo, "README.md", "<!-- rhiza-count: commands -->\ntwo slash commands\n")
    monkeypatch.chdir(repo)
    assert cpc.main([]) == 0
    assert "1 marked claim(s) checked" in capsys.readouterr().out


def test_main_exits_1_and_lists_each_violation(repo, capsys):
    write(repo, "README.md", "<!-- rhiza-count: commands -->\nnine slash commands\n")
    assert cpc.main(["--root", str(repo)]) == 1
    err = capsys.readouterr().err
    assert "Prose count check failed:" in err
    assert "claims 9 commands, but the tree holds 2" in err
