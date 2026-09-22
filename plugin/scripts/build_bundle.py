#!/usr/bin/env python3
"""Generate the client-agnostic skill bundle under ``bundle/``.

The ten commands and nine procedures are the only Claude-bound part of this plugin —
12,500 lines of ``scripts/`` are stdlib-only Python that any caller can drive, and
``docs/headless.md`` already documents them as a standalone surface. What binds the
prose is a short list: ``${CLAUDE_PLUGIN_ROOT}``, the ``allowed-tools`` /
``argument-hint`` / ``disable-model-invocation`` frontmatter keys, a handful of tool
names, and ``AskUserQuestion``. The ``SKILL.md`` format around them is now an open
standard that many clients read.

So this is a **translation, not a port**: same prose, same scripts, with the four
bindings rewritten or restated in a preamble every client can read.

Three decisions worth knowing before changing it:

**It writes a build artifact, and that artifact is committed.** A client is pointed at a
checkout; asking users to run a build first would defeat the purpose. The cost of a
generated file in git is drift, which is why ``--check`` runs as a hook — the same
arrangement ``render_command_docs.py`` already uses for the docs reference blocks.

**It copies no Python.** ``${RHIZA_ROOT}`` is the checkout, so a bundled skill reaches
``${RHIZA_ROOT}/plugin/scripts/<name>.py`` — the same file the plugin runs, under the
same eight gates. A bundle carrying its own copy would be a second ``scripts/`` tree to
keep in step, and this repository has already decided against a second implementation of
anything.

**It restates what it removes.** ``allowed-tools`` is dropped from the frontmatter,
because a client that ignores the key enforces nothing and the reader is left believing
otherwise. The binaries it named reappear in the preamble as prose, where they are a
fact the model can act on rather than a permission the client silently didn't apply.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/build_bundle.py [--root DIR] [--check]

Writes the bundle by default, printing what changed. With ``--check`` it writes nothing
and exits 1 if the committed bundle is stale, which is how the hook runs it.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Mapping
from pathlib import Path

from _rhiza_layout import (
    BUNDLE_DIR,
    BUNDLE_PROMPTS_DIR,
    BUNDLE_SKILLS_DIR,
    PROMPTS_DIR,
    SKILL_FILE,
    SKILLS_DIR,
    command_files,
)

# The frontmatter block, and one `key: value` line inside it.
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_FIELD = re.compile(r"^([a-z-]+):[ \t]*(.*)$", re.M)
# A binary named in `allowed-tools`, e.g. `Bash(make*)`.
_BINARY = re.compile(r"Bash\(([a-zA-Z0-9_.-]+)\*?\)")

# Every bundled skill is namespaced. A folder of skills is a shared namespace in most
# clients, and `docs`, `status` and `release` are names somebody else will also want.
_PREFIX = "rhiza-"

# Applied in order, so the specific paths win before the bare variable catch-all.
_REWRITES = (
    ("${CLAUDE_PLUGIN_ROOT}/scripts/", "${RHIZA_ROOT}/plugin/scripts/"),
    ("${CLAUDE_PLUGIN_ROOT}/prompts/", f"${{RHIZA_ROOT}}/{BUNDLE_PROMPTS_DIR}/"),
    ("${CLAUDE_PLUGIN_ROOT}", "${RHIZA_ROOT}/plugin"),
    (f"{PROMPTS_DIR}/", f"{BUNDLE_PROMPTS_DIR}/"),
)


def rewrite_paths(body: str) -> str:
    """Point every plugin-root path at ``${RHIZA_ROOT}`` instead.

    The procedures move — the bundle carries its own translated copies — while the
    scripts do not, which is why the two halves resolve to different places.

    >>> rewrite_paths('Run "${CLAUDE_PLUGIN_ROOT}/scripts/sync.py" .')
    'Run "${RHIZA_ROOT}/plugin/scripts/sync.py" .'
    >>> rewrite_paths("Read plugin/prompts/pr-base.md")
    'Read bundle/prompts/pr-base.md'
    """
    for old, new in _REWRITES:
        body = body.replace(old, new)
    return body


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return the frontmatter fields of *text* and the body after it.

    A file with no frontmatter yields no fields and its whole text as the body, which is
    what every procedure is: they carry none by rule 2 of ``check_prompt_wiring.py``.

    >>> split_frontmatter("---\\ndescription: hi\\n---\\n\\nbody\\n")
    ({'description': 'hi'}, 'body\\n')
    >>> split_frontmatter("just prose\\n")
    ({}, 'just prose\\n')
    """
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}, text
    fields = {key: value.strip() for key, value in _FIELD.findall(match.group(1))}
    return fields, text[match.end() :].lstrip("\n")


def binaries(allowed_tools: str) -> list[str]:
    """Return the shell binaries an ``allowed-tools`` line permits, in order.

    >>> binaries("Bash(git*), Bash(uv*), Read, AskUserQuestion")
    ['git', 'uv']
    >>> binaries("Read")
    []
    """
    return _BINARY.findall(allowed_tools)


def _source_note(source: str) -> list[str]:
    """Return the "this file is generated" opening of a preamble."""
    return [
        f"> **Portable copy of `{source}`, generated by",
        "> `plugin/scripts/build_bundle.py`. Edit the source and run `make bundle` —",
        "> an edit here is overwritten.**",
        ">",
    ]


def _shared_notes() -> list[str]:
    """Return the preamble bullets every bundled file carries.

    These are the four bindings the translation cannot rewrite away: a path variable
    only Claude Code sets, a slash-command spelling only it resolves, tool names that
    differ per client, and a question tool most clients do not have.
    """
    return [
        "> - **`${RHIZA_ROOT}`** is your `rhiza-claude` checkout. Export it, or",
        ">   substitute the path wherever it appears. Any remark below about the",
        ">   variable being empty in a source checkout is Claude Code's spelling of the",
        ">   same idea — `${RHIZA_ROOT}` replaces it, and the repo-relative fallbacks do",
        ">   not apply, because you are working in the *user's* repo, not in this one.",
        "> - **`/rhiza:<name>`** names another skill in this bundle, `rhiza-<name>`.",
        ">   Invoke it however your client invokes skills.",
        "> - **Tools.** `Read`, `Edit` and `Write` read and write files; `Grep` and",
        ">   `Glob` search; `Bash` is a shell in the user's repo. Use your equivalents.",
        "> - **`AskUserQuestion`** is a multiple-choice question put to the user. With no",
        ">   such tool, ask in plain text, number the options, and **wait for a reply**:",
        ">   where the procedure says nothing is created without an explicit selection,",
        ">   that holds however the question was asked.",
    ]


def _frontmatter_notes(fields: Mapping[str, str]) -> list[str]:
    """Return the bullets restating the frontmatter keys the bundle drops.

    Dropping them silently is the failure this avoids: a client that ignores
    ``allowed-tools`` enforces nothing, so the permission surface changes while the
    reader has no way to notice. Restated as prose, the same facts still bind.

    ``$ARGUMENTS`` rides along with the argument hint for the same reason. Claude Code
    substitutes it before the model ever sees the text; elsewhere it arrives literally,
    and a model that does not know that runs the command against the string.
    """
    notes = []
    if hint := fields.get("argument-hint"):
        notes.append(f"> - **Arguments:** {hint.strip(chr(34))}.")
        notes.append(">   The text below writes `$ARGUMENTS` for what the user passed;")
        notes.append(">   substitute it yourself if your client does not.")
    if found := binaries(fields.get("allowed-tools", "")):
        listed = ", ".join(f"`{binary}`" for binary in found)
        notes.append(f"> - **Runs:** {listed}. Nothing here enforces that list, where the")
        notes.append(">   plugin's frontmatter did — your client has to permit them.")
    if fields.get("disable-model-invocation") == "true":
        notes.append("> - **Never run this on your own initiative** — only when the user")
        notes.append(">   asks for it by name.")
    return notes


def preamble(source: str, fields: Mapping[str, str]) -> str:
    """Return the block prepended to one bundled file."""
    lines = [*_source_note(source), *_shared_notes(), *_frontmatter_notes(fields)]
    return "\n".join(lines) + "\n"


def render_command(name: str, text: str) -> str:
    """Return the bundled ``SKILL.md`` for command *name*.

    The frontmatter is reduced to the two fields the open format requires, and ``name``
    is added — which the plugin spelling must *not* carry, since there the directory
    already decides the command. That is the one place the two formats contradict each
    other, and it is why this is generated rather than edited in place.
    """
    fields, body = split_frontmatter(text)
    source = f"{SKILLS_DIR}/{name}/{SKILL_FILE}"
    header = f"---\nname: {_PREFIX}{name}\ndescription: {fields.get('description', '')}\n---\n"
    return f"{header}\n{preamble(source, fields)}\n{rewrite_paths(body)}"


def render_procedure(name: str, text: str) -> str:
    """Return the bundled copy of procedure *name*.

    No frontmatter is added: a procedure is not a skill, and giving it one is how it
    would become invocable in a client that scans the directory — the exact property
    ``prompts/`` exists to deny.
    """
    fields, body = split_frontmatter(text)
    return f"{preamble(f'{PROMPTS_DIR}/{name}.md', fields)}\n{rewrite_paths(body)}"


def _first_sentence(description: str) -> str:
    """Return the first sentence of *description*, for the bundle's index table.

    >>> _first_sentence("Sync the repo. Runs no gates.")
    'Sync the repo.'
    >>> _first_sentence("No full stop here")
    'No full stop here'
    """
    head, separator, _ = description.partition(". ")
    return head + separator.strip()


def render_readme(commands: list[tuple[str, str]]) -> str:
    """Return the bundle's own README, listing *commands* as ``(name, description)``."""
    rows = "\n".join(
        f"| `{_PREFIX}{name}` | {_first_sentence(description)} |" for name, description in commands
    )
    return f"""# rhiza, for any agent

**Generated by `plugin/scripts/build_bundle.py`. Edit `plugin/`, then run `make bundle`
— edits here are overwritten.**

The same commands the Claude Code plugin ships, translated for any client that reads the
open `SKILL.md` format. The prose is unchanged; what differs is that the Claude-specific
bindings have been rewritten or restated, because a client that silently ignores them
would leave the reader believing something the run no longer does.

## Use it

```bash
git clone https://github.com/Jebel-Quant/rhiza-claude.git ~/.local/share/rhiza-claude
export RHIZA_ROOT=~/.local/share/rhiza-claude
```

Then point your client at `$RHIZA_ROOT/{BUNDLE_SKILLS_DIR}` — copy or symlink the
directories into wherever it loads skills from. Each one is self-contained apart from
two things it reaches by path: the scripts under `$RHIZA_ROOT/plugin/scripts/`, and the
procedures under `$RHIZA_ROOT/{BUNDLE_PROMPTS_DIR}/`.

`uv` and `git` must be on PATH; there is nothing to install beyond them, since every
script is stdlib-only Python.

## What is here

| Skill | What it does |
| --- | --- |
{rows}

The procedures under `prompts/` are **not** skills and must not be installed as any:
they are steps a skill reaches with a file read, and several are shared. A client that
scanned them as skills would offer the user half a workflow.

## What you give up against the plugin

- **The `PreToolUse` guard.** In Claude Code a hook makes three rules structural: one
  bare `make` per gate, never force-push, never push to the default branch. Here they
  are prose, promised by the skills that make them — so a client with hooks of its own
  is worth wiring up, and one without needs the rules honoured by the model.
- **The tool allow-list.** `allowed-tools` is a Claude Code key; the binaries each skill
  runs are restated in its preamble instead, as a fact rather than an enforcement.
- **`AskUserQuestion`.** Where a skill asks the user to choose, ask in plain text and
  wait for an explicit answer. Every "nothing happens without a selection" rule holds
  however the question was put.

## Without an agent at all

The deterministic half runs with no model in the loop — see `docs/headless.md`, which
maps each command to the scripts underneath it.
"""


def bundle_files(root: Path) -> dict[str, str]:
    """Return every file the bundle should contain, as ``path -> content``."""
    files: dict[str, str] = {}
    index: list[tuple[str, str]] = []
    for name, path in command_files(root):
        text = path.read_text(encoding="utf-8")
        files[f"{BUNDLE_SKILLS_DIR}/{_PREFIX}{name}/{SKILL_FILE}"] = render_command(name, text)
        index.append((name, split_frontmatter(text)[0].get("description", "")))
    for path in sorted((root / PROMPTS_DIR).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        files[f"{BUNDLE_PROMPTS_DIR}/{path.stem}.md"] = render_procedure(path.stem, text)
    files[f"{BUNDLE_DIR}/README.md"] = render_readme(index)
    return files


def existing_files(root: Path) -> set[str]:
    """Return every markdown path currently under the bundle, relative to *root*."""
    bundle = root / BUNDLE_DIR
    if not bundle.is_dir():
        return set()
    return {path.relative_to(root).as_posix() for path in bundle.rglob("*.md")}


def stale(root: Path, files: Mapping[str, str]) -> list[str]:
    """Return every bundle path that is missing, out of date, or no longer generated.

    An orphan matters as much as a stale file: a renamed command leaves its old skill
    behind, and a client pointed at the directory goes on offering it.
    """
    out = [
        f"{rel}: {'missing' if not (root / rel).is_file() else 'out of date'}"
        for rel, content in sorted(files.items())
        if not (root / rel).is_file() or (root / rel).read_text(encoding="utf-8") != content
    ]
    out += [f"{rel}: no longer generated" for rel in sorted(existing_files(root) - set(files))]
    return out


def write(root: Path, files: Mapping[str, str]) -> list[str]:
    """Write the bundle, remove what is no longer generated, and report what changed."""
    changed = []
    for rel, content in sorted(files.items()):
        path = root / rel
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        changed.append(f"  wrote {rel}")
    for rel in sorted(existing_files(root) - set(files)):
        (root / rel).unlink()
        changed.append(f"  removed {rel}")
    _prune(root / BUNDLE_DIR)
    return changed


def _prune(directory: Path) -> None:
    """Remove every empty directory under *directory*, deepest first."""
    if not directory.is_dir():
        return
    for path in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def main(argv: list[str] | None = None) -> int:
    """Write or verify the bundle; exit 1 under ``--check`` when it is stale."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd).")
    parser.add_argument(
        "--check", action="store_true", help="Verify only; write nothing. Exit 1 if stale."
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    files = bundle_files(root)

    if args.check:
        if problems := stale(root, files):
            print("The bundle is out of date. Run `make bundle`.")
            print("\n".join(f"  {problem}" for problem in problems))
            return 1
        print(f"bundle up to date ({len(files)} files)")
        return 0

    if changed := write(root, files):
        print("\n".join(changed))
    print(f"bundle: {len(files)} files")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
