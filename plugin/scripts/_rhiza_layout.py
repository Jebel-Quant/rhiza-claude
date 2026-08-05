#!/usr/bin/env python3
"""Where the plugin sits inside this repository, and where its commands are found.

The shipped plugin lives in ``plugin/`` — ``commands/``, ``skills/`` and ``hooks/`` are
*discovery locations* the Claude Code plugin spec requires at the *plugin* root, and
``.claude-plugin/marketplace.json`` points at it with ``"source": "./plugin"``.
``prompts/`` and ``scripts/`` are this repo's own conventions and sit alongside them.
Everything that builds or checks the repo — ``docs/``, ``tests/``, ``paper/`` and the
top-of-repo prose — stays at the *repository* root.

Four checkers span both halves (``check_command_contracts.py`` reads the commands *and*
the README, ``check_docs_nav.py`` and ``render_command_docs.py`` map commands to docs
pages, ``check_prompt_wiring.py`` compares command names against procedure names).
Without a shared definition each would hardcode ``"plugin"`` — and now the two command
layouts — separately, which is the duplication this repo gates everywhere else. One
name, one place to change.
"""

from __future__ import annotations

from pathlib import Path

PLUGIN_DIR = "plugin"
"""The plugin root, relative to the repository root."""

COMMANDS_DIR = f"{PLUGIN_DIR}/commands"
"""Slash commands in the legacy flat layout, relative to the repository root."""

SKILLS_DIR = f"{PLUGIN_DIR}/skills"
"""Slash commands in the current per-directory layout, relative to the repository root."""

SKILL_FILE = "SKILL.md"
"""The file a skill directory must hold. The directory name, not this, is the command."""

PROMPTS_DIR = f"{PLUGIN_DIR}/prompts"
"""Internal procedures, relative to the repository root."""

SCRIPTS_DIR = f"{PLUGIN_DIR}/scripts"
"""Bundled stdlib-only Python, relative to the repository root."""

PLUGIN_MANIFEST = f"{PLUGIN_DIR}/.claude-plugin/plugin.json"
"""The plugin manifest. Lives with the plugin, not with the marketplace."""

MARKETPLACE_MANIFEST = ".claude-plugin/marketplace.json"
"""The marketplace catalogue. Stays at the repository root, where `add` looks."""


def command_files(root: Path) -> list[tuple[str, Path]]:
    """Every slash command in the plugin at *root*, as ``(name, path)`` sorted by name.

    Both layouts are discovered because Claude Code loads both. ``commands/<name>.md``
    is the legacy flat spelling; ``skills/<name>/SKILL.md`` is the current one, and the
    docs describe the former as "Skills as flat Markdown files". Either way *name* is
    the segment that follows ``/rhiza:`` — for a skill that is the **directory** name,
    since ``SKILL.md`` is the same basename for every one of them.

    A name claimed by both layouts is returned twice rather than silently deduplicated;
    ``check_command_contracts.py`` reports it, because which file wins at runtime is not
    something this repo should be resting on.
    """
    found = [(path.stem, path) for path in (root / COMMANDS_DIR).glob("*.md")]
    found += [(path.parent.name, path) for path in (root / SKILLS_DIR).glob(f"*/{SKILL_FILE}")]
    return sorted(found)
