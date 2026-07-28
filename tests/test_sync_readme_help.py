"""Tests for the README `make help` sync (`scripts/sync_readme_help.py`).

Behind `/rhiza:docs`. This script edits a file humans wrote, so the contract is
narrow and the tests are about restraint: replace only the fenced block's contents,
no-op when the marker is absent, and stay byte-identical on a second run.
"""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

import pytest
import sync_readme_help as srh

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make not available")

_MAKEFILE = textwrap.dedent("""\
    .DEFAULT_GOAL := help

    .PHONY: help test
    help:
    \t@echo "test    run the tests"
    \t@echo "fmt     format the code"

    test:
    \t@echo running
    """)

_README = textwrap.dedent(f"""\
    # widget

    Hand-written intro that must survive.

    ## Development

    {srh.MARKER}

    ```
    stale    old target list
    ```

    ## License

    MIT.
    """)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with a `help` target and a README containing the marker + fence."""
    (tmp_path / "Makefile").write_text(_MAKEFILE)
    (tmp_path / "README.md").write_text(_README)
    return tmp_path


# --- helpers -----------------------------------------------------------------


def test_find_makefile_prefers_the_conventional_names(tmp_path):
    assert srh.find_makefile(tmp_path) is None
    (tmp_path / "GNUmakefile").write_text("help:\n")
    assert srh.find_makefile(tmp_path).name == "GNUmakefile"


def test_has_help_target_asks_make_not_the_file(tmp_path):
    """Resolution is make's job, and a text scan gets it wrong both ways."""
    target = tmp_path / "Makefile"
    target.write_text("help:\n\t@echo hi\n")
    assert srh.has_help_target(target)
    target.write_text("test:\n\t@echo hi\n")
    assert not srh.has_help_target(target)
    # A default goal without a target is not resolvable, though a text scan for
    # `.DEFAULT_GOAL := help` would have claimed it was.
    target.write_text(".DEFAULT_GOAL := help\n")
    assert not srh.has_help_target(target)


def test_has_help_target_sees_through_an_include(tmp_path):
    """The bug that silently disabled this in every rhiza repo.

    A managed repo's root Makefile is essentially `include .rhiza/rhiza.mk`, and the
    `help` target lives in the included file — so grepping the root answered "no" for
    exactly the repos the sync exists to serve.
    """
    (tmp_path / ".rhiza").mkdir()
    (tmp_path / ".rhiza" / "rhiza.mk").write_text("help:\n\t@echo from-the-include\n")
    root = tmp_path / "Makefile"
    root.write_text("include .rhiza/rhiza.mk\n")
    assert "help:" not in root.read_text()  # not in the root at all
    assert srh.has_help_target(root)


def test_clean_help_output_strips_colour_and_chatter():
    raw = (
        "make[1]: Entering directory '/x'\n"
        "\x1b[36mtest\x1b[0m    run the tests\n"
        "make[1]: Leaving directory '/x'\n"
    )
    assert srh.clean_help_output(raw) == "test    run the tests"


def test_clean_help_output_trims_blank_edges():
    assert srh.clean_help_output("\n\n  a  \n\n") == "  a"


def test_find_block_locates_the_fence_after_the_marker():
    lines = [srh.MARKER, "", "```", "body", "```", "after"]
    assert srh.find_block(lines) == (3, 4)


def test_find_block_without_a_marker():
    assert srh.find_block(["# title", "```", "x", "```"]) is None


def test_find_block_with_a_marker_but_no_fence():
    assert srh.find_block([srh.MARKER, "", "just prose"]) is None


def test_find_block_with_an_unterminated_fence():
    assert srh.find_block([srh.MARKER, "```", "body"]) is None


# --- the happy path ----------------------------------------------------------


def test_refreshes_only_the_fenced_block(repo):
    result = srh.sync_readme_help(repo)
    assert result["status"] == "refreshed"

    text = (repo / "README.md").read_text()
    assert "test    run the tests" in text
    assert "fmt     format the code" in text
    assert "stale    old target list" not in text
    # Everything around the block is untouched.
    assert "Hand-written intro that must survive." in text
    assert "## License" in text
    assert srh.MARKER in text
    assert text.count("```") == 2


def test_is_idempotent(repo):
    srh.sync_readme_help(repo)
    once = (repo / "README.md").read_text()

    result = srh.sync_readme_help(repo)

    assert result["status"] == "unchanged"
    assert (repo / "README.md").read_text() == once


def test_fills_an_empty_fence(repo):
    """A freshly scaffolded README has the marker and an empty block."""
    (repo / "README.md").write_text(f"# widget\n\n{srh.MARKER}\n\n```\n```\n")
    assert srh.sync_readme_help(repo)["status"] == "refreshed"
    assert "test    run the tests" in (repo / "README.md").read_text()


def test_preserves_a_missing_trailing_newline(repo):
    (repo / "README.md").write_text(_README.rstrip("\n"))
    srh.sync_readme_help(repo)
    assert not (repo / "README.md").read_text().endswith("\n")


# --- the no-op paths ---------------------------------------------------------


def test_skips_when_there_is_no_readme(tmp_path):
    (tmp_path / "Makefile").write_text(_MAKEFILE)
    result = srh.sync_readme_help(tmp_path)
    assert result["status"] == "skipped"
    assert "no README.md" in result["note"]


def test_skips_when_there_is_no_makefile(tmp_path):
    (tmp_path / "README.md").write_text(_README)
    assert "no Makefile" in srh.sync_readme_help(tmp_path)["note"]


def test_skips_when_the_makefile_has_no_help_target(tmp_path):
    (tmp_path / "README.md").write_text(_README)
    (tmp_path / "Makefile").write_text("test:\n\t@echo hi\n")
    assert "cannot resolve a `help` target" in srh.sync_readme_help(tmp_path)["note"]


def test_skips_a_hand_written_readme_without_the_marker(repo):
    """The defining restraint: never invent a place to put the target list."""
    original = "# widget\n\nA hand-written README with no marker at all.\n"
    (repo / "README.md").write_text(original)

    result = srh.sync_readme_help(repo)

    assert result["status"] == "skipped"
    assert "marker" in result["note"]
    assert (repo / "README.md").read_text() == original  # byte-for-byte


def test_honours_a_custom_readme_name(repo):
    (repo / "README.md").unlink()
    (repo / "docs.md").write_text(_README)
    assert srh.sync_readme_help(repo, "docs.md")["status"] == "refreshed"


def test_reports_a_failing_make_help(repo):
    (repo / "Makefile").write_text(".DEFAULT_GOAL := help\nhelp:\n\t@exit 3\n")
    result = srh.sync_readme_help(repo)
    assert result["status"] == "failed"
    assert result["exit_code"] == srh.EXIT_MAKE_FAILED


def test_skips_when_make_is_absent(repo, monkeypatch):
    monkeypatch.setattr(srh.shutil, "which", lambda _: None)
    assert "make is not on PATH" in srh.sync_readme_help(repo)["note"]


# --- main() / CLI -----------------------------------------------------------


def test_main_json_output(repo, capsys):
    rc = srh.main([str(repo), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["status"] == "refreshed"


def test_main_text_output_on_success(repo, capsys):
    assert srh.main([str(repo)]) == 0
    assert "refreshed" in capsys.readouterr().out


def test_main_text_output_on_skip(tmp_path, capsys):
    assert srh.main([str(tmp_path)]) == 0
    assert "skipped" in capsys.readouterr().err


def test_main_returns_2_when_make_help_fails(repo, capsys):
    (repo / "Makefile").write_text(".DEFAULT_GOAL := help\nhelp:\n\t@exit 3\n")
    assert srh.main([str(repo)]) == srh.EXIT_MAKE_FAILED
    assert "failed" in capsys.readouterr().err


# --- end-to-end: /docs against a real synced repo -----------------------------


def test_e2e_docs_syncs_the_make_help_block(synced_repo_copy):
    """The `make help` sync, against the real template's colourised help output.

    The fixtures use a hand-written help target; this one exercises the genuine
    `.rhiza/rhiza.mk` help, which emits ANSI colour and dozens of targets — the input
    the sanitiser was written for.
    """
    repo = synced_repo_copy
    readme = repo / "README.md"
    readme.write_text(
        f"# widget\n\nIntro that must survive.\n\n## Development\n\n{srh.MARKER}\n\n```\n```\n"
    )

    first = srh.sync_readme_help(repo)
    assert first["status"] == "refreshed", first
    body = readme.read_text()
    assert "Intro that must survive." in body
    assert "\x1b[" not in body, "ANSI escapes leaked into the README"
    assert "Entering directory" not in body, "recursive-make chatter leaked in"
    # The real rhiza.mk provides many targets; a couple that should be listed.
    assert "test" in body and "help" in body

    second = srh.sync_readme_help(repo)
    assert second["status"] == "unchanged", "a second run must be a no-op"
    assert readme.read_text() == body


def test_e2e_docs_leaves_a_marker_less_readme_alone(synced_repo_copy):
    """The README the /init chain produced has no marker — it must stay byte-identical."""
    readme = synced_repo_copy / "README.md"
    before = readme.read_text()
    assert srh.MARKER not in before, "fixture unexpectedly has the marker"

    result = srh.sync_readme_help(synced_repo_copy)

    assert result["status"] == "skipped"
    assert readme.read_text() == before
