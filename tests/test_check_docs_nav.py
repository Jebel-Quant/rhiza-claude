"""Tests for the docs/nav parity checker (`scripts/check_docs_nav.py`).

`CONTRIBUTING.md` requires a docs page and a nav entry for every command and
procedure. This is the check that makes the requirement real, so each rule is tested
twice — that it fires on a broken tree, and that it stays quiet on a sound one. A gate
that cannot fail is a green light with no teeth.
"""

from __future__ import annotations

from pathlib import Path

import check_docs_nav as cdn
import pytest

_ROOT = Path(__file__).resolve().parents[1]

_MKDOCS = """\
site_name: demo

nav:
  - Home: index.md
  - Commands:
      - demo: commands/demo.md
  - Internals:
      - proc: internals/proc.md

theme:
  name: material
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal tree in parity: one command, one procedure, both paged and navigable."""
    for directory in ("commands", "prompts", "docs/commands", "docs/internals"):
        (tmp_path / directory).mkdir(parents=True)
    (tmp_path / "commands" / "demo.md").write_text("# demo\n")
    (tmp_path / "prompts" / "proc.md").write_text("# proc\n")
    (tmp_path / "docs" / "commands" / "demo.md").write_text("# demo page\n")
    (tmp_path / "docs" / "internals" / "proc.md").write_text("# proc page\n")
    (tmp_path / "mkdocs.yml").write_text(_MKDOCS)
    return tmp_path


# --- the sound baseline -------------------------------------------------------


def test_a_tree_in_parity_has_no_violations(repo):
    assert cdn.check_docs_nav(repo) == []


# --- rule 1: the page exists --------------------------------------------------


def test_flags_a_command_with_no_docs_page(repo):
    (repo / "commands" / "fresh.md").write_text("# fresh\n")
    assert "commands/fresh.md has no page at docs/commands/fresh.md" in cdn.check_docs_nav(repo)


def test_flags_a_procedure_with_no_docs_page(repo):
    (repo / "prompts" / "fresh.md").write_text("# fresh\n")
    assert "prompts/fresh.md has no page at docs/internals/fresh.md" in cdn.check_docs_nav(repo)


# --- rule 2: the page is in the nav -------------------------------------------


def test_flags_a_page_that_is_not_in_the_nav(repo):
    """The orphan direction mkdocs --strict cannot see."""
    (repo / "commands" / "extra.md").write_text("# extra\n")
    (repo / "docs" / "commands" / "extra.md").write_text("# extra page\n")
    violations = cdn.check_docs_nav(repo)
    assert "docs/commands/extra.md exists but is not in mkdocs.yml's nav" in violations


def test_a_nav_entry_spelled_with_the_docs_prefix_counts(repo):
    """`docs/commands/x.md` and `commands/x.md` both mean the same page."""
    (repo / "mkdocs.yml").write_text(_MKDOCS.replace("commands/demo.md", "docs/commands/demo.md"))
    assert cdn.check_docs_nav(repo) == []


# --- rule 3: no orphan page ---------------------------------------------------


def test_flags_a_page_whose_command_was_removed(repo):
    (repo / "docs" / "commands" / "retired.md").write_text("# stale instructions\n")
    violations = cdn.check_docs_nav(repo)
    assert (
        "docs/commands/retired.md has no matching commands/retired.md — orphan page" in violations
    )


# --- rule 4: no dangling nav entry --------------------------------------------


def test_flags_a_nav_entry_pointing_at_a_missing_page(repo):
    (repo / "docs" / "commands" / "demo.md").unlink()
    (repo / "commands" / "demo.md").unlink()
    violations = cdn.check_docs_nav(repo)
    assert "mkdocs.yml nav points at docs/commands/demo.md, which does not exist" in violations


# --- nav parsing --------------------------------------------------------------


def test_nav_targets_reads_every_md_path(repo):
    assert cdn.nav_targets(repo / "mkdocs.yml") == {
        "index.md",
        "commands/demo.md",
        "internals/proc.md",
    }


def test_nav_targets_stops_at_the_next_top_level_key(repo):
    """`theme:` ends the block — a later `*.md` elsewhere in the file is not a nav entry."""
    assert "material.md" not in cdn.nav_targets(repo / "mkdocs.yml")
    (repo / "mkdocs.yml").write_text(_MKDOCS + "\nextra_css:\n  - not-a-page.md\n")
    assert "not-a-page.md" not in cdn.nav_targets(repo / "mkdocs.yml")


def test_nav_targets_handles_a_nav_that_runs_to_end_of_file(tmp_path):
    path = tmp_path / "mkdocs.yml"
    path.write_text("site_name: x\n\nnav:\n  - Home: index.md\n")
    assert cdn.nav_targets(path) == {"index.md"}


def test_nav_targets_on_a_missing_file_is_empty(tmp_path):
    assert cdn.nav_targets(tmp_path / "absent.yml") == set()


def test_nav_targets_on_a_file_without_a_nav_key_is_empty(tmp_path):
    path = tmp_path / "mkdocs.yml"
    path.write_text("site_name: x\ntheme:\n  name: material\n")
    assert cdn.nav_targets(path) == set()


def test_a_root_without_the_directories_is_vacuously_sound(tmp_path):
    assert cdn.check_docs_nav(tmp_path) == []


# --- main() / CLI -------------------------------------------------------------


def test_main_passes_on_a_tree_in_parity(repo, capsys):
    assert cdn.main(["--root", str(repo)]) == 0
    assert "docs and nav are in parity" in capsys.readouterr().out


def test_main_reports_each_violation(repo, capsys):
    (repo / "commands" / "fresh.md").write_text("# fresh\n")
    assert cdn.main(["--root", str(repo)]) == 1
    err = capsys.readouterr().err
    assert "Docs/nav parity check failed" in err
    assert "✗" in err


# --- the real repo ------------------------------------------------------------


def test_this_repos_docs_and_nav_are_in_parity():
    """The assertion that matters: every shipped command and procedure is documented."""
    assert cdn.check_docs_nav(_ROOT) == []
