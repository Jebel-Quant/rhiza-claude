"""Tests for the command-contract checker (`scripts/check_command_contracts.py`).

This is the integration test for the plugin's prose. The bundled scripts have unit
tests; the markdown that drives them did not, and that is where the expensive failures
came from — a command calling a script that was renamed, or passing a flag that no
longer exists, discovered only when a user ran it mid-task.

Each rule is tested twice: that it fires on a broken fixture, and that it stays quiet
on a sound one. A checker that cannot fail is a green light with no teeth.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import check_command_contracts as ccc
import pytest

_ROOT = Path(__file__).resolve().parents[1]

_GOOD_FRONTMATTER = """\
---
description: A test command.
argument-hint: "[thing]"
allowed-tools: Bash(uv*), Bash(git*), Read
---
"""


@pytest.fixture
def plugin(tmp_path: Path) -> Path:
    """A minimal, contract-clean plugin root with one real bundled script."""
    (tmp_path / "commands").mkdir()
    (tmp_path / "prompts").mkdir()
    (tmp_path / "scripts").mkdir()
    shutil.copy(_ROOT / "scripts" / "init_scaffold.py", tmp_path / "scripts")
    (tmp_path / "commands" / "demo.md").write_text(
        _GOOD_FRONTMATTER + "\nRun it:\n\n```bash\n"
        "uv run python scripts/init_scaffold.py . --host github --ref v1.0.0\n"
        "```\n"
    )
    return tmp_path


def _write(plugin: Path, body: str, *, name: str = "demo.md") -> None:
    """Replace the demo command's body, keeping valid frontmatter."""
    (plugin / "commands" / name).write_text(_GOOD_FRONTMATTER + body)


# --- the sound baseline -------------------------------------------------------


def test_a_clean_plugin_has_no_violations(plugin):
    assert ccc.check_contracts(plugin) == []


# --- rule 1: frontmatter ------------------------------------------------------


@pytest.mark.parametrize("missing", ["description", "argument-hint", "allowed-tools"])
def test_flags_a_command_missing_a_frontmatter_key(plugin, missing):
    kept = [k for k in ("description", "argument-hint", "allowed-tools") if k != missing]
    front = "---\n" + "".join(f"{k}: x\n" for k in kept) + "---\n"
    (plugin / "commands" / "demo.md").write_text(front + "\nbody\n")
    assert any(missing in v for v in ccc.check_contracts(plugin))


def test_flags_a_command_with_no_frontmatter_at_all(plugin):
    (plugin / "commands" / "demo.md").write_text("# no frontmatter\n")
    assert any("missing frontmatter" in v for v in ccc.check_contracts(plugin))


def test_flags_a_procedure_that_has_command_frontmatter(plugin):
    """A procedure isn't invocable, so frontmatter on one is misleading."""
    (plugin / "prompts" / "p.md").write_text(_GOOD_FRONTMATTER + "\nbody\n")
    assert any("not invocable" in v for v in ccc.check_contracts(plugin))


def test_a_procedure_without_frontmatter_is_fine(plugin):
    (plugin / "prompts" / "p.md").write_text("# Procedure\n\nbody\n")
    assert ccc.check_contracts(plugin) == []


# --- rule 2: bash blocks parse ------------------------------------------------


def test_flags_a_bash_block_that_is_not_valid_shell(plugin):
    _write(plugin, '\n```bash\nif [ -z "$X" ; then echo oops\n```\n')
    assert any("not valid shell" in v for v in ccc.check_contracts(plugin))


def test_angle_placeholders_are_not_treated_as_redirects(plugin):
    """`--host <github|gitlab>` is prose, not a shell redirect and pipe."""
    _write(
        plugin, "\n```bash\nuv run python scripts/init_scaffold.py . --host <github|gitlab>\n```\n"
    )
    assert ccc.check_contracts(plugin) == []


def test_a_multi_line_continuation_block_is_valid(plugin):
    _write(
        plugin,
        "\n```bash\nuv run python scripts/init_scaffold.py . \\\n"
        "  --host github \\\n  --ref v1.0.0\n```\n",
    )
    assert ccc.check_contracts(plugin) == []


# --- rules 3 and 4: scripts and their flags -----------------------------------


def test_flags_a_call_to_a_missing_script(plugin):
    _write(plugin, "\n```bash\nuv run python scripts/ghost.py .\n```\n")
    assert any("scripts/ghost.py, which does not exist" in v for v in ccc.check_contracts(plugin))


def test_flags_a_flag_the_script_does_not_accept(plugin):
    """The most likely silent breakage: a CLI renamed out from under the prose."""
    _write(plugin, "\n```bash\nuv run python scripts/init_scaffold.py . --bogus x\n```\n")
    violations = ccc.check_contracts(plugin)
    assert any("passes --bogus" in v and "does not accept it" in v for v in violations)


def test_accepts_every_flag_the_script_declares(plugin):
    _write(
        plugin,
        "\n```bash\nuv run python scripts/init_scaffold.py . --host gitlab "
        "--language go --template-repo o/r --ref v1 --json\n```\n",
    )
    assert ccc.check_contracts(plugin) == []


def test_flags_are_checked_across_a_continuation(plugin):
    """A wrapped invocation must not hide a bad flag on its second line."""
    _write(
        plugin,
        "\n```bash\nuv run python scripts/init_scaffold.py . \\\n"
        "  --host github \\\n  --nope x\n```\n",
    )
    assert any("passes --nope" in v for v in ccc.check_contracts(plugin))


def test_flags_are_checked_when_the_script_path_is_quoted(plugin):
    """The shape every real invocation uses — and one that silently checked nothing.

    With `"${CLAUDE_PLUGIN_ROOT}/scripts/x.py" --flag`, a closing quote sits right
    after `.py`. An argument pattern that demanded whitespace there captured nothing,
    so the checker reported success while verifying no flags at all.
    """
    _write(
        plugin,
        '\n```bash\nuv run python "${CLAUDE_PLUGIN_ROOT}/scripts/init_scaffold.py" . \\\n'
        "  --nope x\n```\n",
    )
    assert any("passes --nope" in v for v in ccc.check_contracts(plugin))


def test_a_quoted_path_with_valid_flags_still_passes(plugin):
    _write(
        plugin,
        "\n```bash\nuv run python "
        '"${CLAUDE_PLUGIN_ROOT}/scripts/init_scaffold.py" . --host github\n```\n',
    )
    assert ccc.check_contracts(plugin) == []


def test_script_flags_extracts_multi_line_add_argument():
    """The scripts use both single- and multi-line argparse styles."""
    flags = ccc.script_flags(_ROOT / "scripts" / "status.py")
    assert {"--json", "--files", "--tree", "--check"} <= flags


def test_script_flags_does_not_leak_between_calls():
    """A flag declared for one argument must not be attributed to the previous one."""
    flags = ccc.script_flags(_ROOT / "scripts" / "check_version_bump.py")
    assert {"--current", "--target-dir", "--json"} <= flags
    assert "--host" not in flags  # belongs to other scripts entirely


# --- rule 5: invoked commands exist -------------------------------------------


def test_flags_an_invocation_of_a_missing_command(plugin):
    _write(plugin, "\nInvoke the `ghost` command via the Skill tool.\n")
    assert any("invoke `ghost`" in v for v in ccc.check_contracts(plugin))


def test_the_invocation_phrase_is_matched_case_insensitively(plugin):
    """It is often capitalised at the start of a sentence or bullet."""
    _write(plugin, "\ninvoke the `ghost` command via the Skill tool\n")
    assert any("invoke `ghost`" in v for v in ccc.check_contracts(plugin))


def test_an_invocation_of_a_real_command_is_fine(plugin):
    (plugin / "commands" / "other.md").write_text(_GOOD_FRONTMATTER + "\nbody\n")
    _write(plugin, "\nInvoke the `other` command via the Skill tool.\n")
    assert ccc.check_contracts(plugin) == []


def test_mentioning_a_retired_command_in_prose_is_allowed(plugin):
    """History is legitimate context; only instructions to *run* something must resolve.

    Flagging a mention would push authors to delete the explanation of what a command
    replaced, which is exactly the context a reader needs.
    """
    _write(plugin, "\nThis absorbs the retired /rhiza:tree and /rhiza:validate commands.\n")
    assert ccc.check_contracts(plugin) == []


# --- rule 6: allowed-tools covers the binaries used ---------------------------


def test_flags_a_binary_not_covered_by_allowed_tools(plugin):
    """An undeclared binary means a permission prompt mid-flow."""
    _write(plugin, "\n```bash\ncurl -sSL https://example.com\n```\n")
    assert any("no Bash(curl*)" in v for v in ccc.check_contracts(plugin))


def test_shell_builtins_need_no_declaration(plugin):
    _write(plugin, '\n```bash\ntest -f x && echo found\nprintf "%s\\n" hi\n```\n')
    assert ccc.check_contracts(plugin) == []


def test_variable_assignments_are_not_binaries(plugin):
    _write(plugin, '\n```bash\nBRANCH="rhiza_$(date +%Y%m%d)"\ngit checkout -b "$BRANCH"\n```\n')
    assert ccc.check_contracts(plugin) == []


def test_a_procedure_is_not_checked_for_allowed_tools(plugin):
    """Procedures have no frontmatter, so they inherit the caller's permissions."""
    (plugin / "prompts" / "p.md").write_text("# P\n\n```bash\ncurl https://example.com\n```\n")
    assert ccc.check_contracts(plugin) == []


# --- helpers ------------------------------------------------------------------


def test_frontmatter_returns_none_without_a_block():
    assert ccc.frontmatter("# just a heading\n") is None
    assert ccc.frontmatter("---\nunterminated\n") is None


def test_bash_blocks_ignores_other_languages():
    text = "```python\nprint(1)\n```\n\n```bash\necho hi\n```\n"
    assert ccc.bash_blocks(text) == ["echo hi\n"]


def test_a_root_without_the_directories_is_vacuously_sound(tmp_path):
    assert ccc.check_contracts(tmp_path) == []


# --- main() / CLI -------------------------------------------------------------


def test_main_passes_on_a_clean_plugin(plugin, capsys):
    assert ccc.main(["--root", str(plugin)]) == 0
    assert "command contracts hold" in capsys.readouterr().out


def test_main_reports_each_violation(plugin, capsys):
    _write(plugin, "\n```bash\nuv run python scripts/ghost.py .\n```\n")
    assert ccc.main(["--root", str(plugin)]) == 1
    err = capsys.readouterr().err
    assert "Command-contract check failed" in err
    assert "✗" in err


# --- the real repo ------------------------------------------------------------


def test_this_plugins_commands_are_executable():
    """The assertion that matters: every shipped command's contract holds."""
    assert ccc.check_contracts(_ROOT) == []
