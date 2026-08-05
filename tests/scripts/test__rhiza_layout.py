"""Tests for `plugin/scripts/_rhiza_layout.py`.

The constants are trivial; what matters is that they still describe the repository.
These assert against the **real tree**, so moving a directory without updating the
layout module fails here rather than in whichever checker imports it next.
"""

from __future__ import annotations

from pathlib import Path

import _rhiza_layout as layout


def test_plugin_dir_exists(repo_root: Path):
    assert (repo_root / layout.PLUGIN_DIR).is_dir()


def test_commands_and_prompts_resolve(repo_root: Path):
    assert (repo_root / layout.SKILLS_DIR).is_dir()
    assert (repo_root / layout.PROMPTS_DIR).is_dir()


def test_the_flat_layout_is_empty_but_still_supported(repo_root: Path):
    """Every command has migrated, so no flat command file is left.

    Asserted as "no `*.md` in it" rather than "the directory is absent", because those
    differ by checkout: git tracks no empty directory, so a fresh clone has no
    `plugin/commands/` at all, while a working copy where the files were `git mv`d away
    keeps the emptied directory until something removes it. Both states are fine; a flat
    command file reappearing is not.

    `COMMANDS_DIR` deliberately stays: `command_files` still reads it, so a flat file
    someone adds back is discovered and held to every contract rather than ignored. That
    is what the synthetic fixtures throughout these tests exercise. Dropping the constant
    would silently make such a file invisible, which is the one outcome worth preventing.
    """
    assert list((repo_root / layout.COMMANDS_DIR).glob("*.md")) == []
    assert layout.command_files(repo_root), "no commands discovered from either layout"


def test_scripts_dir_holds_this_module(repo_root: Path):
    assert (repo_root / layout.SCRIPTS_DIR / "_rhiza_layout.py").is_file()


def test_both_manifests_resolve(repo_root: Path):
    assert (repo_root / layout.PLUGIN_MANIFEST).is_file()
    assert (repo_root / layout.MARKETPLACE_MANIFEST).is_file()


def test_the_two_manifests_live_in_different_places():
    """The marketplace stays at the repo root; the plugin manifest moved with the plugin."""
    assert layout.PLUGIN_MANIFEST.startswith(f"{layout.PLUGIN_DIR}/")
    assert not layout.MARKETPLACE_MANIFEST.startswith(f"{layout.PLUGIN_DIR}/")


def test_marketplace_points_at_the_plugin_dir(repo_root: Path):
    """`source` and PLUGIN_DIR must agree, or an install resolves to the wrong tree."""
    import json

    manifest = json.loads((repo_root / layout.MARKETPLACE_MANIFEST).read_text())
    sources = {entry["source"] for entry in manifest["plugins"]}
    assert sources == {f"./{layout.PLUGIN_DIR}"}


# --- command_files: both layouts ---------------------------------------------


def test_command_files_names_a_flat_command_by_its_file(tmp_path: Path):
    (tmp_path / layout.COMMANDS_DIR).mkdir(parents=True)
    path = tmp_path / layout.COMMANDS_DIR / "status.md"
    path.write_text("---\ndescription: x\n---\n")
    assert layout.command_files(tmp_path) == [("status", path)]


def test_command_files_names_a_skill_by_its_directory(tmp_path: Path):
    """`SKILL.md` is the same basename for every skill, so the directory is the name."""
    (tmp_path / layout.SKILLS_DIR / "maffay").mkdir(parents=True)
    path = tmp_path / layout.SKILLS_DIR / "maffay" / layout.SKILL_FILE
    path.write_text("---\ndescription: x\n---\n")
    assert layout.command_files(tmp_path) == [("maffay", path)]


def test_command_files_ignores_stray_markdown_beside_a_skill(tmp_path: Path):
    """Only `SKILL.md` is discovered, so a skill may bundle its own notes."""
    (tmp_path / layout.SKILLS_DIR / "maffay").mkdir(parents=True)
    (tmp_path / layout.SKILLS_DIR / "maffay" / layout.SKILL_FILE).write_text("x")
    (tmp_path / layout.SKILLS_DIR / "maffay" / "NOTES.md").write_text("y")
    assert [name for name, _ in layout.command_files(tmp_path)] == ["maffay"]


def test_command_files_merges_the_layouts_in_name_order(tmp_path: Path):
    (tmp_path / layout.COMMANDS_DIR).mkdir(parents=True)
    (tmp_path / layout.COMMANDS_DIR / "update.md").write_text("x")
    (tmp_path / layout.COMMANDS_DIR / "docs.md").write_text("x")
    (tmp_path / layout.SKILLS_DIR / "maffay").mkdir(parents=True)
    (tmp_path / layout.SKILLS_DIR / "maffay" / layout.SKILL_FILE).write_text("x")
    assert [name for name, _ in layout.command_files(tmp_path)] == ["docs", "maffay", "update"]


def test_command_files_reports_a_name_claimed_by_both_layouts_twice(tmp_path: Path):
    """Deduplicating here would hide the half-finished migration rule 10 exists to catch."""
    (tmp_path / layout.COMMANDS_DIR).mkdir(parents=True)
    (tmp_path / layout.COMMANDS_DIR / "maffay.md").write_text("x")
    (tmp_path / layout.SKILLS_DIR / "maffay").mkdir(parents=True)
    (tmp_path / layout.SKILLS_DIR / "maffay" / layout.SKILL_FILE).write_text("x")
    assert [name for name, _ in layout.command_files(tmp_path)] == ["maffay", "maffay"]


def test_command_files_is_empty_when_neither_directory_exists(tmp_path: Path):
    assert layout.command_files(tmp_path) == []


def test_command_files_finds_every_shipped_command(repo_root: Path):
    """Against the real tree: moving a command between layouts must not lose it."""
    names = [name for name, _ in layout.command_files(repo_root)]
    assert names == sorted(names)
    assert set(names) == {
        "detach",
        "docs",
        "init",
        "maffay",
        "quality",
        "release",
        "status",
        "update",
    }
