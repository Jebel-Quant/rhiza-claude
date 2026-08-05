#!/usr/bin/env python3
"""Check that the plugin's internal procedures under ``prompts/`` stay wired up.

``commands/*.md`` and ``skills/*/SKILL.md`` are slash commands the user invokes.
``prompts/*.md`` are **internal procedures** a command reaches with the ``Read`` tool —
deliberately outside *both* discovery locations so they cannot be invoked directly.
Nothing at runtime verifies that arrangement, so a rename or a stray file would only
surface as a command failing mid-run, in front of a user. This is that check.

It enforces six rules:

1. every procedure announces itself as **not a slash command**, so a reader (human
   or model) opening one mid-task knows it isn't user-facing;
2. no procedure carries command frontmatter (``allowed-tools``/``argument-hint``),
   which would be misleading and hints the file belongs in a discovery location;
3. no procedure name collides with a command name;
4. every ``prompts/<name>.md`` path mentioned in the repo's prose resolves — a
   dangling reference is a command that breaks when it reaches that step;
5. no procedure is orphaned — each is referenced by at least one command or
   procedure, and none is invoked "via the Skill tool", which only works for real
   commands;
6. no shipped prose names a discovery location this plugin does not have.

Rule 6 is the one that guards the *reasoning* rather than the wiring. Rules 1–5 assert
that a procedure declares itself un-invocable and stays reachable; none of them reads
*why* the prose says it is un-invocable. When all eight commands moved to ``skills/``
and ``commands/`` stopped existing, eleven shipped files still explained themselves as
"in ``prompts/``, not ``commands/``" — an argument from a directory that is no longer
there, which a model can reasonably read as a constraint that no longer binds. Rule 6
fails the build on that class of claim.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/check_prompt_wiring.py [--root DIR]

Exits 0 when the wiring is sound, 1 (listing every violation) otherwise.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _rhiza_layout import PLUGIN_DIR, PROMPTS_DIR, command_files

_NOT_A_COMMAND = "Not a slash command"
_FRONTMATTER_KEYS = ("allowed-tools:", "argument-hint:")
_PROMPT_REF = re.compile(r"prompts/([a-zA-Z0-9_-]+)\.md")
_SKILL_INVOCATION = re.compile(r"`([a-zA-Z0-9_-]+)` command via the Skill tool")

_DISCOVERY_DIRS = ("agents", "bin", "commands", "hooks", "monitors", "skills")
"""The directory names Claude Code scans at a plugin root.

Deliberately not "every directory the prose mentions": `.rhiza/`, `tests/`, `docs/` and
`scripts/` name a *managed repo's* layout far more often than this plugin's, so gating
them would be noise. These six are unambiguous — prose naming one is making a claim
about where Claude Code looks for components.
"""

_PATH_CHARS = r"[\w${}./-]"
_LAYOUT_PATH = re.compile(rf"(?<!{_PATH_CHARS})({_PATH_CHARS}*?)({'|'.join(_DISCOVERY_DIRS)})/")
_PLUGIN_PREFIXES = ("", f"{PLUGIN_DIR}/", "${CLAUDE_PLUGIN_ROOT}/")
_LAYOUT_EXEMPT = re.compile(r"<!--\s*rhiza-layout-exempt:\s*([a-z]+)/\s+(\S[^>]*?)\s*-->")


def _names(directory: Path) -> list[str]:
    """Return the sorted stems of the markdown files directly in *directory*."""
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.md"))


def _shipped_prose(root: Path) -> list[Path]:
    """Return every markdown file the plugin ships — the text a model reads at runtime.

    Repo-level prose is deliberately excluded. ``CLAUDE.md`` narrates this layout
    *including which directories are gone*, so "``plugin/commands/`` no longer exists"
    is a true and useful sentence there and a rule-6 violation here. The distinction is
    the point: rule 6 governs claims a model acts on mid-task, not claims a maintainer
    reads while changing the layout.
    """
    return sorted([*(path for _, path in command_files(root)), *(root / PROMPTS_DIR).glob("*.md")])


def _prose_files(root: Path) -> list[Path]:
    """Return every markdown file whose prompt references should resolve."""
    return sorted(
        [
            *(path for _, path in command_files(root)),
            *(root / PROMPTS_DIR).glob("*.md"),
            *root.glob("*.md"),
        ]
    )


def check_declares_internal(prompts_dir: Path) -> list[str]:
    """Rule 1: each procedure states that it is not a slash command."""
    return [
        f"prompts/{name}.md does not say {_NOT_A_COMMAND!r}"
        for name in _names(prompts_dir)
        if _NOT_A_COMMAND not in (prompts_dir / f"{name}.md").read_text()
    ]


def check_no_command_frontmatter(prompts_dir: Path) -> list[str]:
    """Rule 2: procedures carry no command frontmatter."""
    violations = []
    for name in _names(prompts_dir):
        text = (prompts_dir / f"{name}.md").read_text()
        if text.startswith("---"):
            violations.append(f"prompts/{name}.md opens with command frontmatter")
        violations += [
            f"prompts/{name}.md declares {key!r}, which only applies to commands"
            for key in _FRONTMATTER_KEYS
            if key in text
        ]
    return violations


def check_no_name_collisions(root: Path, prompts_dir: Path) -> list[str]:
    """Rule 3: a name is either a command or a procedure, never both.

    The command side spans both layouts, so moving a command into ``skills/`` cannot
    quietly free up its name for a procedure to take.
    """
    commands = {name for name, _ in command_files(root)}
    both = sorted(commands & set(_names(prompts_dir)))
    return [f"{name!r} exists as both a command and a procedure" for name in both]


def check_references_resolve(root: Path) -> list[str]:
    """Rule 4: every ``prompts/<name>.md`` mentioned in prose exists."""
    violations = []
    for path in _prose_files(root):
        for name in sorted(set(_PROMPT_REF.findall(path.read_text()))):
            if not (root / PROMPTS_DIR / f"{name}.md").is_file():
                rel = path.relative_to(root)
                violations.append(f"{rel} references missing prompts/{name}.md")
    return violations


def check_no_orphans_and_no_skill_calls(root: Path) -> list[str]:
    """Rule 5: every procedure is referenced, and none is invoked as a command."""
    prompts = set(_names(root / PROMPTS_DIR))
    referenced: set[str] = set()
    violations = []

    for path in _prose_files(root):
        text = path.read_text()
        # A file referencing itself doesn't make it reachable.
        own = path.stem if path.parent.name == "prompts" else None
        referenced |= {name for name in _PROMPT_REF.findall(text) if name != own}
        for name in _SKILL_INVOCATION.findall(text):
            if name in prompts:
                rel = path.relative_to(root)
                violations.append(
                    f"{rel} invokes {name!r} via the Skill tool, but it is a procedure, "
                    "not a command — reach it with Read"
                )

    violations += [
        f"prompts/{name}.md is never referenced — no command can reach it"
        for name in sorted(prompts - referenced)
    ]
    return violations


def check_no_dead_layout_paths(root: Path) -> list[str]:
    """Rule 6: shipped prose never names a discovery location the plugin lacks.

    A reference is only checked when it is unprefixed, or reached the way a skill
    actually reaches the plugin root — ``plugin/`` in a source checkout,
    ``${CLAUDE_PLUGIN_ROOT}/`` at runtime. ``docs/skills/`` is a site path and passes.

    The escape hatch is an HTML comment naming the directory and giving a reason:
    ``<!-- rhiza-layout-exempt: commands/ the repo under assessment, not this plugin -->``.
    It is scoped to that directory in that file, and the reason is mandatory — a
    pragma without one does not match, so the violation stands.
    """
    violations = []
    for path in _shipped_prose(root):
        text = path.read_text()
        exempt = {name for name, _ in _LAYOUT_EXEMPT.findall(text)}
        found = {name for prefix, name in _LAYOUT_PATH.findall(text) if prefix in _PLUGIN_PREFIXES}
        violations += [
            f"{path.relative_to(root)} refers to {name}/, which this plugin does not have"
            for name in sorted(found - exempt)
            if not (root / PLUGIN_DIR / name).is_dir()
        ]
    return violations


def check_wiring(root: Path) -> list[str]:
    """Run every rule against *root*; return all violations."""
    prompts_dir = root / PROMPTS_DIR
    return [
        *check_declares_internal(prompts_dir),
        *check_no_command_frontmatter(prompts_dir),
        *check_no_name_collisions(root, prompts_dir),
        *check_references_resolve(root),
        *check_no_orphans_and_no_skill_calls(root),
        *check_no_dead_layout_paths(root),
    ]


def main(argv: list[str] | None = None) -> int:
    """Entry point: check the wiring and return an exit code."""
    parser = argparse.ArgumentParser(description="Check the plugin's prompt wiring.")
    parser.add_argument("--root", default=".", help="Plugin root (default: current directory).")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    violations = check_wiring(root)
    if violations:
        print("Prompt-wiring check failed:", file=sys.stderr)
        for violation in violations:
            print(f"  ✗ {violation}", file=sys.stderr)
        return 1

    count = len(_names(root / PROMPTS_DIR))
    print(f"prompt wiring is sound ({count} internal procedure(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
