"""Tests for the portable-bundle generator (`scripts/build_bundle.py`).

The bundle is a committed build artifact, which makes two failure modes worth pinning
rather than one. The obvious one is a bad translation — a path left pointing at a
variable no other client sets. The other is **silence**: a stale bundle that still looks
plausible, or an orphan skill left behind by a renamed command and still offered to
users. So every rule here is tested in both directions, and `--check` is tested on a
tree it should pass as well as one it should fail.
"""

from __future__ import annotations

from pathlib import Path

import build_bundle as bb
import pytest

_SKILL = """\
---
description: Do the thing. And then stop.
argument-hint: "[a path]  (optional)"
allowed-tools: Bash(git*), Bash(uv*), Read, AskUserQuestion
disable-model-invocation: true
---

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/sync.py"` and then read
`${CLAUDE_PLUGIN_ROOT}/prompts/pr-base.md`; in a source checkout, plugin/prompts/pr-base.md.
"""

_PROCEDURE = """\
# pr-base (internal procedure)

> **Not a slash command.**

Invoke `"${CLAUDE_PLUGIN_ROOT}/scripts/status.py"`.
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal source tree: one command, one procedure, no bundle yet."""
    skill = tmp_path / "plugin" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(_SKILL, encoding="utf-8")
    prompts = tmp_path / "plugin" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "pr-base.md").write_text(_PROCEDURE, encoding="utf-8")
    return tmp_path


def test_rewrite_paths_scripts_resolve_to_the_checkout() -> None:
    """Scripts are not copied, so they keep pointing at `plugin/scripts/`."""
    assert (
        bb.rewrite_paths('"${CLAUDE_PLUGIN_ROOT}/scripts/sync.py"')
        == '"${RHIZA_ROOT}/plugin/scripts/sync.py"'
    )


def test_rewrite_paths_procedures_resolve_to_the_bundle() -> None:
    """Procedures *are* copied and translated, so they point at the bundle's copy."""
    assert (
        bb.rewrite_paths("${CLAUDE_PLUGIN_ROOT}/prompts/pr-base.md")
        == "${RHIZA_ROOT}/bundle/prompts/pr-base.md"
    )


def test_rewrite_paths_repo_relative_procedure_paths_move_too() -> None:
    """The source-checkout fallback names `plugin/prompts/`, which has moved."""
    assert bb.rewrite_paths("see plugin/prompts/license.md") == "see bundle/prompts/license.md"


def test_rewrite_paths_bare_variable_still_resolves() -> None:
    """A sentence naming the variable alone must not be left mentioning it."""
    assert "CLAUDE_PLUGIN_ROOT" not in bb.rewrite_paths("`${CLAUDE_PLUGIN_ROOT}` is empty")


def test_rewrite_paths_scripts_are_not_sent_to_the_bundle() -> None:
    """The catch-all must not undo the specific rewrite that ran before it."""
    assert "bundle/scripts" not in bb.rewrite_paths("${CLAUDE_PLUGIN_ROOT}/scripts/sync.py")


def test_split_frontmatter_fields_and_body() -> None:
    """The fields come back parsed and the body with its leading blank lines gone."""
    fields, body = bb.split_frontmatter("---\nname: x\ndescription: y\n---\n\nbody\n")
    assert fields == {"name": "x", "description": "y"}
    assert body == "body\n"


def test_split_frontmatter_no_frontmatter() -> None:
    """A procedure carries none, and must survive unchanged."""
    assert bb.split_frontmatter("# heading\n") == ({}, "# heading\n")


def test_binaries_only_bash_entries_count() -> None:
    """`Read` and `AskUserQuestion` are tools, not binaries."""
    assert bb.binaries("Bash(make*), Read, Bash(gh*), AskUserQuestion") == ["make", "gh"]


def test_binaries_none() -> None:
    """A command that shells out to nothing gets no line at all."""
    assert bb.binaries("Read, Write") == []


def test_preamble_names_its_source() -> None:
    """A reader who wants to change the file has to be sent to the source."""
    assert "plugin/skills/demo/SKILL.md" in bb.preamble("plugin/skills/demo/SKILL.md", {})


def test_preamble_shared_notes_are_unconditional() -> None:
    """Every file gets the four bindings, frontmatter or not."""
    block = bb.preamble("plugin/prompts/pr-base.md", {})
    assert "${RHIZA_ROOT}" in block
    assert "AskUserQuestion" in block


def test_preamble_restates_the_dropped_keys() -> None:
    """The permission surface changes silently unless the binaries are restated."""
    fields, _ = bb.split_frontmatter(_SKILL)
    block = bb.preamble("plugin/skills/demo/SKILL.md", fields)
    assert "`git`, `uv`" in block
    assert "$ARGUMENTS" in block
    assert "only when the user" in block


def test_preamble_omits_what_is_not_declared() -> None:
    """No hint, no binaries, no opt-out: three bullets that must not appear."""
    block = bb.preamble("plugin/prompts/pr-base.md", {})
    assert "**Arguments:**" not in block
    assert "**Runs:**" not in block
    assert "only when the user" not in block


def test_render_command_frontmatter_is_the_open_minimum() -> None:
    """`name` is required here and forbidden in the source — hence generation."""
    fields, _ = bb.split_frontmatter(bb.render_command("demo", _SKILL))
    assert fields == {"name": "rhiza-demo", "description": "Do the thing. And then stop."}


def test_render_command_claude_only_keys_are_gone() -> None:
    """A key no client enforces must not sit in the frontmatter implying it does."""
    rendered = bb.render_command("demo", _SKILL)
    assert "allowed-tools:" not in rendered
    assert "disable-model-invocation:" not in rendered


def test_render_command_body_survives_translated() -> None:
    """The prose is the product; only its paths change."""
    rendered = bb.render_command("demo", _SKILL)
    assert "${RHIZA_ROOT}/plugin/scripts/sync.py" in rendered
    assert "CLAUDE_PLUGIN_ROOT" not in rendered


def test_render_procedure_stays_un_invocable() -> None:
    """Frontmatter is what would make a client offer it as a skill."""
    rendered = bb.render_procedure("pr-base", _PROCEDURE)
    assert not rendered.startswith("---")
    assert "Not a slash command" in rendered


def test_render_procedure_paths_translated() -> None:
    """A procedure reaches the scripts by the same variable a skill does."""
    assert "${RHIZA_ROOT}/plugin/scripts/status.py" in bb.render_procedure("x", _PROCEDURE)


def test_render_readme_lists_every_skill_by_its_namespaced_name() -> None:
    """The name in the table is the one a client will show the user."""
    readme = bb.render_readme([("demo", "Do the thing. And then stop.")])
    assert "| `rhiza-demo` | Do the thing. |" in readme


def test_render_readme_keeps_a_description_with_no_full_stop() -> None:
    """Truncating on a separator that isn't there must not empty the cell."""
    assert "| `rhiza-x` | no full stop |" in bb.render_readme([("x", "no full stop")])


def test_bundle_files_one_skill_one_procedure_one_readme(repo: Path) -> None:
    """Namespaced skill directory, same-stem procedure, and the index."""
    assert set(bb.bundle_files(repo)) == {
        "bundle/skills/rhiza-demo/SKILL.md",
        "bundle/prompts/pr-base.md",
        "bundle/README.md",
    }


def test_existing_files_absent_bundle_is_empty_not_an_error(repo: Path) -> None:
    """The first run has nothing to compare against."""
    assert bb.existing_files(repo) == set()


def test_existing_files_finds_what_was_written(repo: Path) -> None:
    """Every markdown file under the bundle counts, at any depth."""
    bb.write(repo, bb.bundle_files(repo))
    assert "bundle/README.md" in bb.existing_files(repo)


def test_stale_missing(repo: Path) -> None:
    """Nothing written yet: every file is missing."""
    assert len(bb.stale(repo, bb.bundle_files(repo))) == 3


def test_stale_clean(repo: Path) -> None:
    """A freshly written bundle is quiet, which is what makes the gate usable."""
    files = bb.bundle_files(repo)
    bb.write(repo, files)
    assert bb.stale(repo, files) == []


def test_stale_out_of_date(repo: Path) -> None:
    """An edited bundle file is reported, not silently overwritten by the check."""
    files = bb.bundle_files(repo)
    bb.write(repo, files)
    (repo / "bundle" / "README.md").write_text("hand-edited\n", encoding="utf-8")
    assert bb.stale(repo, files) == ["bundle/README.md: out of date"]


def test_stale_orphan(repo: Path) -> None:
    """A renamed command leaves its old skill behind, still offered to users."""
    files = bb.bundle_files(repo)
    bb.write(repo, files)
    orphan = repo / "bundle" / "skills" / "rhiza-gone"
    orphan.mkdir(parents=True)
    (orphan / "SKILL.md").write_text("stale\n", encoding="utf-8")
    assert bb.stale(repo, files) == ["bundle/skills/rhiza-gone/SKILL.md: no longer generated"]


def test_write_reports_only_what_changed(repo: Path) -> None:
    """A second run is a no-op, so a green build stays quiet."""
    files = bb.bundle_files(repo)
    assert len(bb.write(repo, files)) == 3
    assert bb.write(repo, files) == []


def test_write_removes_the_orphan_and_prunes_its_directory(repo: Path) -> None:
    """An emptied skill directory left behind is a skill with no file in it."""
    files = bb.bundle_files(repo)
    bb.write(repo, files)
    orphan = repo / "bundle" / "skills" / "rhiza-gone"
    orphan.mkdir(parents=True)
    (orphan / "SKILL.md").write_text("stale\n", encoding="utf-8")
    assert any("removed" in line for line in bb.write(repo, files))
    assert not orphan.exists()


def test_write_prune_tolerates_no_bundle(tmp_path: Path) -> None:
    """Pruning runs after every write, including one that wrote nothing."""
    bb._prune(tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


def test_main_writes_and_reports(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The default run writes the bundle and says what it did."""
    assert bb.main(["--root", str(repo)]) == 0
    assert "bundle: 3 files" in capsys.readouterr().out


def test_main_a_second_run_writes_nothing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Re-running prints the count and no change list — a no-op has to look like one."""
    bb.main(["--root", str(repo)])
    capsys.readouterr()
    assert bb.main(["--root", str(repo)]) == 0
    assert capsys.readouterr().out == "bundle: 3 files\n"


def test_main_check_fails_on_a_stale_bundle(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The whole point of committing a generated tree: drift has to turn the build red."""
    assert bb.main(["--root", str(repo), "--check"]) == 1
    assert "Run `make bundle`" in capsys.readouterr().out


def test_main_check_passes_on_a_current_bundle(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """And must not fail on a sound tree, or it would be switched off."""
    bb.main(["--root", str(repo)])
    capsys.readouterr()
    assert bb.main(["--root", str(repo), "--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_this_repo_is_current(repo_root: Path) -> None:
    """`make bundle` has been run for the state of `plugin/` in this commit."""
    assert bb.stale(repo_root, bb.bundle_files(repo_root)) == []


def test_this_repo_every_command_is_bundled(repo_root: Path) -> None:
    """A new command must not be able to arrive without its portable copy."""
    import _rhiza_layout as layout

    names = {f"rhiza-{name}" for name, _ in layout.command_files(repo_root)}
    bundled = {path.parent.name for path in (repo_root / "bundle" / "skills").glob("*/SKILL.md")}
    assert bundled == names


def test_this_repo_no_claude_only_path_survives(repo_root: Path) -> None:
    """One leftover variable is a skill that silently runs nothing, everywhere."""
    leftovers = [
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "bundle").rglob("*.md")
        if "CLAUDE_PLUGIN_ROOT" in path.read_text(encoding="utf-8")
    ]
    assert leftovers == []
