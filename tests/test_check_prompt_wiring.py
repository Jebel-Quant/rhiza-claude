"""Tests for the prompt-wiring checker (`scripts/check_prompt_wiring.py`).

Two jobs: exercise each rule against synthetic plugin roots, and assert the **real**
repo passes — so a rename that breaks a command mid-run fails here first.
"""

from __future__ import annotations

from pathlib import Path

import check_prompt_wiring as cw
import pytest

_ROOT = Path(__file__).resolve().parents[1]

_INTERNAL = """\
# Skeleton (internal procedure)

> **Not a slash command.** `/rhiza:init` reads it.
"""


@pytest.fixture
def plugin(tmp_path: Path) -> Path:
    """A minimal, sound plugin root: one command referencing one procedure."""
    (tmp_path / "commands").mkdir()
    (tmp_path / "prompts").mkdir()
    (tmp_path / "commands" / "init.md").write_text(
        "---\ndescription: x\n---\n\n`Read` prompts/skeleton.md and follow it.\n"
    )
    (tmp_path / "prompts" / "skeleton.md").write_text(_INTERNAL)
    return tmp_path


def test_a_sound_root_has_no_violations(plugin):
    assert cw.check_wiring(plugin) == []


# --- rule 1: declares itself internal ---------------------------------------


def test_flags_a_procedure_that_does_not_declare_itself(plugin):
    (plugin / "prompts" / "skeleton.md").write_text("# Skeleton\n\nJust prose.\n")
    (violation,) = cw.check_wiring(plugin)
    assert "does not say" in violation


# --- rule 2: no command frontmatter -----------------------------------------


def test_flags_command_frontmatter_on_a_procedure(plugin):
    (plugin / "prompts" / "skeleton.md").write_text(
        '---\ndescription: x\nargument-hint: "[n]"\nallowed-tools: Read\n---\n\n'
        "> **Not a slash command.**\n"
    )
    violations = cw.check_wiring(plugin)
    assert any("opens with command frontmatter" in v for v in violations)
    assert any("argument-hint:" in v for v in violations)
    assert any("allowed-tools:" in v for v in violations)


# --- rule 3: no name collisions ---------------------------------------------


def test_flags_a_name_that_is_both_a_command_and_a_procedure(plugin):
    (plugin / "commands" / "skeleton.md").write_text("---\ndescription: x\n---\n")
    violations = cw.check_wiring(plugin)
    assert any("both a command and a procedure" in v for v in violations)


# --- rule 4: references resolve ---------------------------------------------


def test_flags_a_dangling_reference(plugin):
    (plugin / "commands" / "init.md").write_text("`Read` prompts/gone.md and follow it.\n")
    violations = cw.check_wiring(plugin)
    assert any("references missing prompts/gone.md" in v for v in violations)


def test_checks_references_in_root_markdown_too(plugin):
    (plugin / "README.md").write_text("See prompts/nowhere.md for details.\n")
    violations = cw.check_wiring(plugin)
    assert any("references missing prompts/nowhere.md" in v for v in violations)


# --- rule 5: no orphans, no Skill invocations --------------------------------


def test_flags_an_orphaned_procedure(plugin):
    (plugin / "prompts" / "stray.md").write_text(_INTERNAL)
    violations = cw.check_wiring(plugin)
    assert any("prompts/stray.md is never referenced" in v for v in violations)


def test_a_self_reference_does_not_make_a_procedure_reachable(plugin):
    """Mentioning your own path is not a caller."""
    (plugin / "prompts" / "stray.md").write_text(_INTERNAL + "\nSee prompts/stray.md.\n")
    violations = cw.check_wiring(plugin)
    assert any("prompts/stray.md is never referenced" in v for v in violations)


def test_a_procedure_may_be_reached_from_another_procedure(plugin):
    """skeleton -> python-version is the real chain, and must be allowed."""
    (plugin / "prompts" / "python-version.md").write_text(_INTERNAL)
    (plugin / "prompts" / "skeleton.md").write_text(
        _INTERNAL + "\n`Read` prompts/python-version.md and follow it.\n"
    )
    assert cw.check_wiring(plugin) == []


def test_flags_a_procedure_invoked_via_the_skill_tool(plugin):
    (plugin / "commands" / "init.md").write_text(
        "prompts/skeleton.md exists, but this line invokes the "
        "`skeleton` command via the Skill tool instead.\n"
    )
    violations = cw.check_wiring(plugin)
    assert any("via the Skill tool" in v for v in violations)


def test_allows_skill_invocation_of_a_real_command(plugin):
    """Commands may legitimately delegate to other commands."""
    (plugin / "commands" / "update.md").write_text("---\ndescription: x\n---\n")
    (plugin / "commands" / "init.md").write_text(
        "`Read` prompts/skeleton.md, and invoke the `update` command via the Skill tool.\n"
    )
    assert cw.check_wiring(plugin) == []


# --- tolerance for a partial root -------------------------------------------


def test_a_root_without_a_prompts_directory_is_vacuously_sound(tmp_path):
    (tmp_path / "commands").mkdir()
    assert cw.check_wiring(tmp_path) == []


# --- main() / CLI -----------------------------------------------------------


def test_main_passes_on_a_sound_root(plugin, capsys):
    assert cw.main(["--root", str(plugin)]) == 0
    assert "prompt wiring is sound" in capsys.readouterr().out


def test_main_reports_each_violation(plugin, capsys):
    (plugin / "prompts" / "stray.md").write_text("# Stray\n")
    assert cw.main(["--root", str(plugin)]) == 1
    err = capsys.readouterr().err
    assert "Prompt-wiring check failed" in err
    assert "✗" in err


# --- the real repo ----------------------------------------------------------


def test_this_repo_is_wired_correctly():
    """The assertion that actually matters: /init and /update can reach their steps."""
    assert cw.check_wiring(_ROOT) == []


@pytest.mark.parametrize("name", ["install-uv", "pr-base", "skeleton", "license", "python-version"])
def test_the_expected_procedures_exist(name):
    """Pins the current set, so adding or removing one is a deliberate edit here."""
    assert (_ROOT / "prompts" / f"{name}.md").is_file()
    assert not (_ROOT / "commands" / f"{name}.md").exists()


def test_init_and_update_both_start_with_install_uv():
    """Both entry points must install `uv` before anything that depends on it."""
    for command, dependent in (("init.md", "init_scaffold.py"), ("update.md", "sync.py")):
        text = (_ROOT / "commands" / command).read_text()
        assert "prompts/install-uv.md" in text, f"{command} does not follow install-uv"
        assert text.index("prompts/install-uv.md") < text.index(dependent)


def test_skeleton_reaches_python_version():
    """The Python metadata step hangs off the skeleton, not off /init."""
    assert "prompts/python-version.md" in (_ROOT / "prompts" / "skeleton.md").read_text()


@pytest.mark.parametrize("command", ["init.md", "update.md"])
def test_both_entry_points_share_the_pr_base_procedure(command):
    """The 'never push to the default branch' rule lives in one place, not two."""
    assert "prompts/pr-base.md" in (_ROOT / "commands" / command).read_text()


def test_pr_base_is_reached_before_any_commit_is_pushed():
    """The branch must exist before the push, in both callers."""
    for command in ("init.md", "update.md"):
        text = (_ROOT / "commands" / command).read_text()
        assert text.index("prompts/pr-base.md") < text.index("git push")
