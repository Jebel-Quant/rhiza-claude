#!/usr/bin/env python3
"""Where the plugin sits inside this repository.

The shipped plugin lives in ``plugin/`` — its ``commands/``, ``hooks/``, ``prompts/``
and ``scripts/`` are required by the Claude Code plugin spec to sit at the *plugin*
root, and ``.claude-plugin/marketplace.json`` points at it with ``"source":
"./plugin"``. Everything that builds or checks the repo — ``docs/``, ``tests/``,
``paper/`` and the top-of-repo prose — stays at the *repository* root.

Three checkers span both halves (``check_command_contracts.py`` reads the commands
*and* the README, ``check_docs_nav.py`` and ``render_command_docs.py`` map commands to
docs pages). Without a shared constant each would hardcode ``"plugin"`` separately,
which is the duplication this repo gates everywhere else. One name, one place to change.

``check_prompt_wiring.py`` deliberately does **not** import this: it only ever looks at
``commands/`` and ``prompts/``, so its ``--root`` is simply the plugin root and it is
invoked as ``--root plugin``.
"""

from __future__ import annotations

PLUGIN_DIR = "plugin"
"""The plugin root, relative to the repository root."""

COMMANDS_DIR = f"{PLUGIN_DIR}/commands"
"""Slash commands, relative to the repository root."""

PROMPTS_DIR = f"{PLUGIN_DIR}/prompts"
"""Internal procedures, relative to the repository root."""

SCRIPTS_DIR = f"{PLUGIN_DIR}/scripts"
"""Bundled stdlib-only Python, relative to the repository root."""

PLUGIN_MANIFEST = f"{PLUGIN_DIR}/.claude-plugin/plugin.json"
"""The plugin manifest. Lives with the plugin, not with the marketplace."""

MARKETPLACE_MANIFEST = ".claude-plugin/marketplace.json"
"""The marketplace catalogue. Stays at the repository root, where `add` looks."""
