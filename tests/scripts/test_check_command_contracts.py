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

import _rhiza_layout as layout
import check_command_contracts as ccc
import pytest

_GOOD_FRONTMATTER = """\
---
description: A test command.
argument-hint: "[thing]"
allowed-tools: Bash(uv*), Bash(git*), Read
---
"""


@pytest.fixture
def plugin(tmp_path: Path, repo_root: Path) -> Path:
    """A minimal, contract-clean plugin root with one real bundled script."""
    (tmp_path / layout.COMMANDS_DIR).mkdir(parents=True)
    (tmp_path / layout.PROMPTS_DIR).mkdir(parents=True)
    (tmp_path / layout.SCRIPTS_DIR).mkdir(parents=True)
    shutil.copy(repo_root / layout.SCRIPTS_DIR / "init_scaffold.py", tmp_path / layout.SCRIPTS_DIR)
    (tmp_path / layout.COMMANDS_DIR / "demo.md").write_text(
        _GOOD_FRONTMATTER + "\nRun it:\n\n```bash\n"
        "uv run python scripts/init_scaffold.py . --host github --ref v1.0.0\n"
        "```\n",
        encoding="utf-8",
    )
    return tmp_path


def _write_prose(plugin: Path, name: str, body: str) -> None:
    """Write a non-command prose file at the plugin root."""
    (plugin / name).write_text(body, encoding="utf-8")


def _write(plugin: Path, body: str, *, name: str = "demo.md") -> None:
    """Replace the demo command's body, keeping valid frontmatter."""
    (plugin / layout.COMMANDS_DIR / name).write_text(_GOOD_FRONTMATTER + body, encoding="utf-8")


# --- the sound baseline -------------------------------------------------------


def test_a_clean_plugin_has_no_violations(plugin):
    assert ccc.check_contracts(plugin) == []


# --- rule 1: frontmatter ------------------------------------------------------


@pytest.mark.parametrize("missing", ["description", "argument-hint", "allowed-tools"])
def test_flags_a_command_missing_a_frontmatter_key(plugin, missing):
    kept = [k for k in ("description", "argument-hint", "allowed-tools") if k != missing]
    front = "---\n" + "".join(f"{k}: x\n" for k in kept) + "---\n"
    (plugin / layout.COMMANDS_DIR / "demo.md").write_text(front + "\nbody\n", encoding="utf-8")
    assert any(missing in v for v in ccc.check_contracts(plugin))


def test_flags_a_command_with_no_frontmatter_at_all(plugin):
    (plugin / layout.COMMANDS_DIR / "demo.md").write_text("# no frontmatter\n", encoding="utf-8")
    assert any("missing frontmatter" in v for v in ccc.check_contracts(plugin))


def test_flags_a_procedure_that_has_command_frontmatter(plugin):
    """A procedure isn't invocable, so frontmatter on one is misleading."""
    (plugin / layout.PROMPTS_DIR / "p.md").write_text(
        _GOOD_FRONTMATTER + "\nbody\n", encoding="utf-8"
    )
    assert any("not invocable" in v for v in ccc.check_contracts(plugin))


def test_a_procedure_without_frontmatter_is_fine(plugin):
    (plugin / layout.PROMPTS_DIR / "p.md").write_text("# Procedure\n\nbody\n", encoding="utf-8")
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

    With `"${CLAUDE_PLUGINrepo_root}/scripts/x.py" --flag`, a closing quote sits right
    after `.py`. An argument pattern that demanded whitespace there captured nothing,
    so the checker reported success while verifying no flags at all.
    """
    _write(
        plugin,
        '\n```bash\nuv run python "${CLAUDE_PLUGINrepo_root}/scripts/init_scaffold.py" . \\\n'
        "  --nope x\n```\n",
    )
    assert any("passes --nope" in v for v in ccc.check_contracts(plugin))


def test_a_quoted_path_with_valid_flags_still_passes(plugin):
    _write(
        plugin,
        "\n```bash\nuv run python "
        '"${CLAUDE_PLUGINrepo_root}/scripts/init_scaffold.py" . --host github\n```\n',
    )
    assert ccc.check_contracts(plugin) == []


def test_script_flags_extracts_multi_line_add_argument(repo_root: Path):
    """The scripts use both single- and multi-line argparse styles."""
    flags = ccc.script_flags(repo_root / layout.SCRIPTS_DIR / "status.py")
    assert {"--json", "--files", "--tree", "--check"} <= flags


def test_script_flags_does_not_leak_between_calls(repo_root: Path):
    """A flag declared for one argument must not be attributed to the previous one."""
    flags = ccc.script_flags(repo_root / layout.SCRIPTS_DIR / "check_version_bump.py")
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
    (plugin / layout.COMMANDS_DIR / "other.md").write_text(
        _GOOD_FRONTMATTER + "\nbody\n", encoding="utf-8"
    )
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
    (plugin / layout.PROMPTS_DIR / "p.md").write_text(
        "# P\n\n```bash\ncurl https://example.com\n```\n", encoding="utf-8"
    )
    assert ccc.check_contracts(plugin) == []


# --- rule 7: model-invocation policy -------------------------------------------


def _write_opt_out_command(plugin: Path, name: str, declared: str | None) -> None:
    """Write `commands/<name>.md`, optionally declaring the opt-out key."""
    key = f"{ccc._OPT_OUT_KEY}: {declared}\n" if declared is not None else ""
    frontmatter = _GOOD_FRONTMATTER.rstrip("\n").removesuffix("---") + key + "---\n"
    (plugin / layout.COMMANDS_DIR / f"{name}.md").write_text(
        frontmatter + "\nBody.\n", encoding="utf-8"
    )


@pytest.mark.parametrize("name", sorted(ccc._MODEL_INVOCATION_OPT_OUT))
def test_flags_an_opt_out_command_that_does_not_declare_the_key(plugin, name):
    _write_opt_out_command(plugin, name, None)
    violations = ccc.check_contracts(plugin)
    assert any("must declare" in v and name in v for v in violations)


@pytest.mark.parametrize("name", sorted(ccc._MODEL_INVOCATION_OPT_OUT))
def test_an_opt_out_command_declaring_true_is_fine(plugin, name):
    _write_opt_out_command(plugin, name, "true")
    assert ccc.check_contracts(plugin) == []


def test_flags_an_opt_out_command_that_declares_false(plugin):
    """`false` is not merely redundant here — it reverses the policy."""
    _write_opt_out_command(plugin, "detach", "false")
    violations = ccc.check_contracts(plugin)
    assert any("must declare" in v and "found: false" in v for v in violations)


def test_flags_an_ordinary_command_that_declares_the_key(plugin):
    """The other direction: an opt-out nobody reviewed silently hides a command."""
    _write_opt_out_command(plugin, "harmless", "true")
    violations = ccc.check_contracts(plugin)
    assert any("is not in the opt-out set" in v for v in violations)


def test_an_ordinary_command_without_the_key_is_fine(plugin):
    _write_opt_out_command(plugin, "harmless", None)
    assert ccc.check_contracts(plugin) == []


def test_the_policy_is_not_applied_to_procedures(plugin):
    """Rule 1 already rejects frontmatter under prompts/; rule 7 must not double-report."""
    (plugin / layout.PROMPTS_DIR / "release.md").write_text(
        "Not a slash command.\n", encoding="utf-8"
    )
    assert ccc.check_contracts(plugin) == []


def test_a_command_with_no_frontmatter_is_left_to_rule_one(plugin):
    """Rule 7 stays silent rather than piling a second error onto the same cause."""
    (plugin / layout.COMMANDS_DIR / "release.md").write_text("# No frontmatter\n", encoding="utf-8")
    violations = ccc.check_contracts(plugin)
    assert any("missing frontmatter" in v for v in violations)
    assert not any(ccc._OPT_OUT_KEY in v for v in violations)


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


def test_main_defaults_to_the_working_directory(plugin, monkeypatch, capsys):
    """The hook passes no `--root`, so a broken default would gate nothing at all."""
    _write(plugin, "\n```bash\nuv run python scripts/ghost.py .\n```\n")
    monkeypatch.chdir(plugin)
    assert ccc.main([]) == 1
    assert "scripts/ghost.py" in capsys.readouterr().err


def test_main_reports_each_violation(plugin, capsys):
    _write(plugin, "\n```bash\nuv run python scripts/ghost.py .\n```\n")
    assert ccc.main(["--root", str(plugin)]) == 1
    err = capsys.readouterr().err
    assert "Command-contract check failed" in err
    assert "✗" in err


# --- the real repo ------------------------------------------------------------


def test_this_plugins_commands_are_executable(repo_root: Path):
    """The assertion that matters: every shipped command's contract holds."""
    assert ccc.check_contracts(repo_root) == []


# --- rule 1b: the frontmatter must actually parse ------------------------------


def test_flags_a_description_with_an_unquoted_colon(plugin):
    """The bug that shipped in five of seven commands.

    `description: procedures under prompts/: install-uv` is not valid YAML — the second
    `: ` reads as a nested mapping, so the whole block fails to load and the command's
    metadata is lost. The original key check was a substring search, which passed.
    """
    (plugin / layout.COMMANDS_DIR / "demo.md").write_text(
        "---\n"
        "description: delegates to internal procedures: install-uv, skeleton\n"
        'argument-hint: "[x]"\n'
        "allowed-tools: Read\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )
    violations = ccc.check_contracts(plugin)
    assert any("unquoted `: `" in v and "description" in v for v in violations)


def test_a_quoted_value_may_contain_a_colon(plugin):
    """Quoting is the escape hatch, so the rule must not forbid colons outright."""
    (plugin / layout.COMMANDS_DIR / "demo.md").write_text(
        "---\n"
        'description: "delegates to internal procedures: install-uv"\n'
        'argument-hint: "[x]"\n'
        "allowed-tools: Read\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )
    assert ccc.check_contracts(plugin) == []


def test_a_block_scalar_may_contain_a_colon(plugin):
    (plugin / layout.COMMANDS_DIR / "demo.md").write_text(
        "---\n"
        "description: >-\n"
        "  delegates to internal procedures: install-uv\n"
        'argument-hint: "[x]"\n'
        "allowed-tools: Read\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )
    assert ccc.check_contracts(plugin) == []


@pytest.mark.parametrize(
    ("value", "flagged"),
    [
        ("plain text", False),
        ("a url https://example.com/x", False),  # `://` is not `: `
        ("time 12:30 today", False),  # no space after the colon
        ("key: value", True),
        ("trailing colon:", False),  # nothing follows, so no mapping
        ('"quoted: value"', False),
        ("'single: quoted'", False),
        (">-", False),
    ],
)
def test_unquoted_mapping_colon(value, flagged):
    assert ccc.unquoted_mapping_colon(value) is flagged


def test_parse_frontmatter_reports_a_malformed_line(plugin):
    mapping, problems = ccc.parse_frontmatter("description: ok\nnot-a-pair\n")
    assert mapping == {"description": "ok"}
    assert any("not `key: value`" in p for p in problems)


def test_parse_frontmatter_ignores_continuations_and_comments():
    mapping, problems = ccc.parse_frontmatter(
        "# a comment\ndescription: >-\n  wrapped: continuation\nallowed-tools: Read\n"
    )
    assert set(mapping) == {"description", "allowed-tools"}
    assert problems == []


def test_this_plugins_frontmatter_all_parses(repo_root: Path):
    """The assertion that would have caught it: every shipped command loads.

    Discovered via `command_files`, not by globbing one directory — a command moved into
    `skills/` must not drop out of the check that its frontmatter parses.
    """
    commands = layout.command_files(repo_root)
    assert commands, "no commands discovered — the layout moved without this test"
    for name, path in commands:
        block = ccc.frontmatter(path.read_text(encoding="utf-8"))
        assert block is not None, f"{name} has no frontmatter"
        mapping, problems = ccc.parse_frontmatter(block)
        assert problems == [], f"{name}: {problems}"
        assert {"description", "argument-hint", "allowed-tools"} <= set(mapping)


# --- rule 10: one file per command --------------------------------------------


def _as_skill(plugin: Path, name: str, body: str = "\nBody.\n") -> Path:
    """Write `skills/<name>/SKILL.md`, with frontmatter the other rules accept."""
    (plugin / layout.SKILLS_DIR / name).mkdir(parents=True, exist_ok=True)
    path = plugin / layout.SKILLS_DIR / name / layout.SKILL_FILE
    path.write_text(_GOOD_FRONTMATTER + body, encoding="utf-8")
    return path


def test_a_command_in_the_skill_layout_is_contract_clean(plugin):
    """The move must be invisible to every other rule."""
    (plugin / layout.COMMANDS_DIR / "demo.md").unlink()
    _as_skill(plugin, "demo")
    assert ccc.check_contracts(plugin) == []


def test_flags_a_command_defined_by_both_layouts(plugin):
    """A copy that was never followed by a delete ships `/rhiza:demo` twice."""
    _as_skill(plugin, "demo")
    violations = ccc.check_contracts(plugin)
    assert (
        f"skills/demo/{layout.SKILL_FILE}: `demo` is also defined by commands/demo.md"
        " — a command is one file, not two" in violations
    )


def test_two_differently_named_skills_are_not_a_collision(plugin):
    _as_skill(plugin, "one")
    _as_skill(plugin, "two")
    assert ccc.check_contracts(plugin) == []


def test_a_skill_violation_names_its_directory_not_its_basename(plugin):
    """`SKILL.md` identifies nothing on its own, so the path carries the skill name."""
    (plugin / layout.COMMANDS_DIR / "demo.md").unlink()
    _as_skill(plugin, "demo", "\n```bash\nuv run python scripts/gone.py\n```\n")
    violations = ccc.check_contracts(plugin)
    assert f"skills/demo/{layout.SKILL_FILE}: invokes scripts/gone.py" in violations[0]


def test_prose_may_invoke_a_command_that_lives_as_a_skill(plugin):
    """Rule 5 keys off the command surface, not off a directory listing."""
    _as_skill(plugin, "other")
    _write(plugin, "\nThen invoke the `other` command via the Skill tool.\n")
    assert ccc.check_contracts(plugin) == []


# --- rule 7: prose outside commands/ ------------------------------------------


def test_flags_a_dead_script_reference_in_contributing(plugin):
    """The exact historical failure, pinned.

    `CONTRIBUTING.md` told contributors to run `scripts/bump_version.py`, which has
    never existed. Two things let it survive: it sat in inline backticks rather than a
    ```bash block, and no gate read the top-of-repo prose at all.
    """
    (plugin / "CONTRIBUTING.md").write_text(
        "Bump with `uv run --no-project python scripts/bump_version.py`.\n", encoding="utf-8"
    )
    violations = ccc.check_contracts(plugin)
    assert any("scripts/bump_version.py, which does not exist" in v for v in violations)


def test_flags_a_bad_flag_in_prose(plugin):
    _write_prose(plugin, "README.md", "Run `python scripts/init_scaffold.py . --nope x`.\n")
    assert any("passes --nope" in v for v in ccc.check_contracts(plugin))


def test_a_real_script_and_flag_in_prose_is_fine(plugin):
    _write_prose(plugin, "README.md", "Run `python scripts/init_scaffold.py . --host github`.\n")
    assert ccc.check_contracts(plugin) == []


def test_a_tests_scripts_path_is_not_read_as_a_shipped_script(plugin):
    """Prose naming a test file must not be mistaken for a missing script.

    `tests/scripts/test_platform_cli.py` ends in the same `scripts/<name>.py` shape a
    shipped script does, so the reference scanner matched its tail and demanded
    `plugin/scripts/test_platform_cli.py`. Real regression: it broke `make lint` the
    moment the suite moved to `tests/scripts/` to mirror the plugin.
    """
    _write_prose(plugin, "README.md", "Half of `tests/scripts/test_platform_cli.py` needs glab.\n")
    assert ccc.check_contracts(plugin) == []


def test_the_docs_site_is_checked_too(plugin):
    page = plugin / "docs" / "skills" / "demo.md"
    page.parent.mkdir(parents=True)
    page.write_text("It calls `scripts/ghost.py`.\n", encoding="utf-8")
    assert any("docs/skills/demo.md" in v for v in ccc.check_contracts(plugin))


def test_generated_reports_are_not_treated_as_prose(plugin):
    """`docs/reports/` is a coverage dump, not something anyone wrote."""
    report = plugin / "docs" / "reports" / "index.md"
    report.parent.mkdir(parents=True)
    report.write_text("`scripts/ghost.py`\n", encoding="utf-8")
    assert ccc.check_contracts(plugin) == []


def test_prose_files_absent_is_not_a_violation(plugin):
    """A repo need not have every one of these files."""
    assert ccc.prose_files(plugin) == []
    assert ccc.check_contracts(plugin) == []


def test_this_repos_prose_references_all_resolve(repo_root: Path):
    """The assertion that matters: no dead script reference anywhere a reader looks."""
    scripts_dir = repo_root / layout.SCRIPTS_DIR
    violations = [
        v
        for path in ccc.prose_files(repo_root)
        for v in ccc.check_script_references(
            path.relative_to(repo_root).as_posix(), path.read_text(encoding="utf-8"), scripts_dir
        )
    ]
    assert violations == []


# --- rule 9: prose naming a test file that no longer exists --------------------


def test_flags_a_dead_test_reference_in_the_docs(plugin):
    """The exact historical failure, pinned — the other half of rule 7.

    `docs/development.md` told contributors to run `RHIZA_E2E=1 uvx pytest
    tests/test_init_e2e.py`. That file was folded into `test_init_scaffold.py` in #29 and
    the instruction stayed, because the reference scanner only read `scripts/`.
    """
    (plugin / "tests").mkdir()
    _write_prose(plugin, "CONTRIBUTING.md", "Run `uvx pytest tests/test_init_e2e.py`.\n")
    violations = ccc.check_contracts(plugin)
    assert any("tests/test_init_e2e.py, which does not exist" in v for v in violations)


def test_a_live_test_reference_is_fine(plugin):
    (plugin / "tests").mkdir()
    (plugin / "tests" / "test_real.py").write_text("", encoding="utf-8")
    _write_prose(plugin, "CONTRIBUTING.md", "Run `uvx pytest tests/test_real.py`.\n")
    assert ccc.check_contracts(plugin) == []


def test_the_templates_own_synced_tests_are_not_ours_to_resolve(plugin):
    """`.rhiza/tests/test_pyproject.py` is a file the sync delivers, documented here.

    Matching it would make the gate demand a file this repo must not contain.
    """
    (plugin / "tests").mkdir()
    _write_prose(
        plugin, "CONTRIBUTING.md", "The synced `.rhiza/tests/test_pyproject.py` asserts.\n"
    )
    assert ccc.check_contracts(plugin) == []


def test_a_test_glob_or_placeholder_is_not_a_reference(plugin):
    """`tests/*.py` and `tests/test_<name>.py` are patterns, not files."""
    (plugin / "tests").mkdir()
    _write_prose(
        plugin,
        "CLAUDE.md",
        "`tests/` mirrors `scripts/`: `tests/test_<name>.py` per module, `tests/*.py` pass.\n",
    )
    assert ccc.check_contracts(plugin) == []


def test_this_repos_prose_test_references_all_resolve(repo_root: Path):
    """No dead test reference anywhere a contributor looks."""
    tests_dir = repo_root / "tests"
    violations = [
        v
        for path in ccc.prose_files(repo_root)
        for v in ccc.check_test_references(
            path.relative_to(repo_root).as_posix(), path.read_text(encoding="utf-8"), tests_dir
        )
    ]
    assert violations == []


# --- gaps that mutation testing found (`make mutate`) --------------------------
#
# This checker *is* a gate, so a mutant that survives here is a gate silently not gating —
# the same failure class as `_rhiza_lock`'s `_PROTECTED`, one level up. Every assertion
# below kills a mutant that lived through the suite at 100% line and branch coverage,
# grouped by what the mutation revealed rather than by rule.


@pytest.mark.parametrize(
    "builtin",
    ["cd", "echo", "test", "if", "then", "else", "fi", "for", "do", "done", "printf", "export"],
)
def test_each_shell_builtin_needs_no_declaration(plugin, builtin):
    """Every exempt word, one at a time — the list is what stops rule 6 crying wolf.

    Spelled out rather than parametrized over `ccc._SHELL_BUILTINS`, because iterating the
    constant under test cannot detect a word dropped from it. Ten of the twelve could be
    corrupted with the suite green, and the symptom would be rule 6 demanding
    `Bash(then*)` — a false positive, which is how a gate gets switched off.
    """
    _write(plugin, f"\n```bash\n{builtin}\n```\n")
    assert not any(f"runs `{builtin}`" in v for v in ccc.check_contracts(plugin))


def test_a_comment_line_is_not_a_binary(plugin):
    """Prose blocks are full of `# …` lines; reading one as a command means `runs \\`#\\``."""
    _write(plugin, '\n```bash\n# Explain the next line.\necho "hi"\n```\n')
    assert ccc.check_contracts(plugin) == []


def test_a_flag_at_the_start_of_a_line_is_not_a_binary(plugin):
    """An unwrapped continuation puts a `--flag` first; it is not something to declare."""
    _write(plugin, '\n```bash\ngit commit -m "x"\n--amend\n```\n')
    assert not any("runs `--amend`" in v for v in ccc.check_contracts(plugin))


def test_every_undeclared_binary_is_reported_not_just_the_first(plugin):
    """The scan must not stop at the first line it skips, in either skipping arm."""
    _write(plugin, "\n```bash\n# a comment\nBRANCH=x\ncurl https://a\nwget https://b\n```\n")
    violations = ccc.check_contracts(plugin)
    assert any("no Bash(curl*)" in v for v in violations)
    assert any("no Bash(wget*)" in v for v in violations)


def test_a_slash_command_in_a_bash_block_must_exist(plugin):
    """Rule 5's other half: the `/rhiza:<name>` form inside a block, not just the phrase."""
    _write(plugin, "\n```bash\n# hand off\n/rhiza:ghost\n```\n")
    assert any("invoke `ghost`" in v for v in ccc.check_contracts(plugin))


def test_slash_commands_are_collected_from_every_block(plugin):
    """Accumulated across blocks, not overwritten by the last one nor intersected."""
    _write(plugin, "\n```bash\n/rhiza:one\n```\n\n```bash\n/rhiza:two\n```\n")
    violations = ccc.check_contracts(plugin)
    assert any("invoke `one`" in v for v in violations)
    assert any("invoke `two`" in v for v in violations)


def test_a_missing_script_does_not_end_the_scan(plugin):
    """The `continue` after a dead reference must not swallow the rest of the block."""
    _write(
        plugin,
        "\n```bash\nuv run python scripts/ghost.py .\n"
        "uv run python scripts/init_scaffold.py . --nope x\n```\n",
    )
    violations = ccc.check_contracts(plugin)
    assert any("scripts/ghost.py, which does not exist" in v for v in violations)
    assert any("passes --nope" in v for v in violations)


def test_a_missing_script_in_prose_does_not_end_the_scan(plugin):
    """Rule 7's copy of the same arm, over prose rather than blocks."""
    _write_prose(
        plugin,
        "README.md",
        "Run `scripts/ghost.py`, then `scripts/init_scaffold.py . --nope x`.\n",
    )
    violations = ccc.check_contracts(plugin)
    assert any("scripts/ghost.py, which does not exist" in v for v in violations)
    assert any("passes --nope" in v for v in violations)


def test_prose_flag_violations_accumulate_within_a_file(plugin):
    """Two bad flags in one prose file: `violations +=`, not `violations =`."""
    _write_prose(plugin, "README.md", "Run `scripts/init_scaffold.py . --nope x --alsonope y`.\n")
    violations = ccc.check_contracts(plugin)
    assert any("passes --nope" in v for v in violations)
    assert any("passes --alsonope" in v for v in violations)


def test_prose_violations_accumulate_across_files(plugin):
    """Each prose file adds to the report; the last one must not replace it."""
    _write_prose(plugin, "README.md", "Run `scripts/ghost.py`.\n")
    _write_prose(plugin, "CONTRIBUTING.md", "Run `scripts/phantom.py`.\n")
    violations = ccc.check_contracts(plugin)
    assert any("README.md: names scripts/ghost.py" in v for v in violations)
    assert any("CONTRIBUTING.md: names scripts/phantom.py" in v for v in violations)


@pytest.mark.parametrize("name", ["README.md", "CONTRIBUTING.md", "CLAUDE.md", "SECURITY.md"])
def test_every_top_of_repo_prose_file_is_read(plugin, name):
    """The four filenames, one at a time — a name dropped from the tuple gates nothing.

    Two of the four could be corrupted with the suite still green, and the failure mode is
    silent: `CLAUDE.md` may then name any script it likes.
    """
    _write_prose(plugin, name, "Run `scripts/ghost.py`.\n")
    assert any(f"{name}: names scripts/ghost.py" in v for v in ccc.check_contracts(plugin))


def test_a_wrapped_invocation_in_prose_is_joined(plugin):
    """Rule 7 must join continuations too, or a bad flag hides on the second line."""
    _write_prose(
        plugin,
        "README.md",
        "```\nuv run python scripts/init_scaffold.py . \\\n  --nope x\n```\n",
    )
    assert any("passes --nope" in v for v in ccc.check_contracts(plugin))


def test_the_violation_names_which_bash_block_failed(plugin):
    """Blocks are numbered from 1, and the number is how a reader finds the right one."""
    _write(plugin, '\n```bash\necho fine\n```\n\n```bash\nif [ -z "$X" ; then echo oops\n```\n')
    violations = ccc.check_contracts(plugin)
    assert any("bash block 2 is not valid shell" in v for v in violations)


def test_an_empty_frontmatter_block_is_not_a_missing_one(plugin):
    """`---\\n\\n---` parses as an empty mapping; reporting it as absent hides the keys."""
    assert ccc.frontmatter("---\n\n---\n") == ""
    (plugin / layout.COMMANDS_DIR / "demo.md").write_text("---\n\n---\n\nbody\n", encoding="utf-8")
    violations = ccc.check_contracts(plugin)
    assert not any("missing frontmatter" in v for v in violations)
    assert any("has no `description`" in v for v in violations)


def test_a_malformed_frontmatter_line_reports_its_line_number():
    """The body starts at file line 2, so `start=2` is the number a reader can jump to."""
    _, problems = ccc.parse_frontmatter("not-a-pair\ndescription: ok\n")
    assert any("line 2 is not `key: value`" in p for p in problems)


def test_a_malformed_line_does_not_stop_the_parse():
    """`continue`, not `break`: the keys after a bad line are still declared."""
    mapping, problems = ccc.parse_frontmatter(
        "not-a-pair\ndescription: x\nargument-hint: y\nallowed-tools: Read\n"
    )
    assert set(mapping) == {"description", "argument-hint", "allowed-tools"}
    assert len(problems) == 1


def test_a_singly_indented_continuation_is_still_a_continuation():
    """Continuation detection reads the *first* character, not the second.

    With `line[1]`, a value wrapped under one space is parsed as a key line — so
    `allowed-tools:` wrapped that way yields a bogus `key: value` problem instead of being
    skipped.
    """
    mapping, problems = ccc.parse_frontmatter("description: >-\n one: wrapped\n")
    assert set(mapping) == {"description"}
    assert problems == []


@pytest.mark.parametrize("leader", ["A", "X", "z", "0"])
def test_a_plain_scalar_is_checked_whatever_letter_it_starts_with(leader):
    """Only quotes and block scalars are exempt — the exemption is a fixed four.

    Widening that set by one character is enough to stop the check firing on a real value,
    and nothing noticed.
    """
    assert ccc.unquoted_mapping_colon(f"{leader}foo: bar") is True
