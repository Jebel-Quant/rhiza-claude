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
    assert (repo_root / layout.COMMANDS_DIR).is_dir()
    assert (repo_root / layout.PROMPTS_DIR).is_dir()


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
