#!/usr/bin/env python3
"""Generate the reference block on every command and procedure docs page.

``check_docs_nav.py`` already asserts that a page *exists* and is *navigable*. That is
the weakest thing that can go wrong. The likelier drift is **content**: a page that
still describes a flag, a tool permission or a caller that the command no longer has.
Nothing checked that, and prose-to-prose comparison cannot.

So the facts that drift mechanically are generated from the source of truth — the
command and procedure files themselves — and spliced into each page between markers:

- **Invocation** — the name plus its ``argument-hint``, so a renamed argument cannot
  linger in the docs.
- **Allowed tools** — the ``allowed-tools`` frontmatter, which appeared **nowhere** in
  the docs site before this. It is the single most security-relevant fact about a
  command and it was undocumented.
- **Model-invocable** — whether the command carries ``disable-model-invocation``.
  ``check_command_contracts.py`` asserts the policy holds; this publishes it.
- **Read by** (procedures) — which commands actually ``Read`` this procedure, derived
  by scanning for the reference rather than trusted to a human.

**What is deliberately not generated: the prose.** An early sketch of this had the whole
page rendered from the command body. That is wrong, and the page sizes say why —
``docs/commands/maffay.md`` is *longer* than ``commands/maffay.md``. The command body is
instructions to a model; the docs page explains the command to a person. They are
different documents with different audiences, and generating one from the other would
have deleted real documentation. The generated block is therefore **additive**: it
appends a reference table and never touches a hand-written line.

Usage:
  uv run --python 3.12 --no-project python \
      plugin/scripts/render_command_docs.py [--root DIR] [--check]

Writes the blocks by default. With ``--check`` it writes nothing and exits 1 if any
page is out of date, which is how the pre-commit hook runs it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _rhiza_layout import COMMANDS_DIR, PROMPTS_DIR

_BEGIN = "<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->"
_END = "<!-- generated:end -->"

# The frontmatter block, and one `key: value` line inside it.
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_FIELD = re.compile(r"^([a-z-]+):[ \t]*(.*)$", re.M)

# A `prompts/<name>.md` reference, used to work out which commands read a procedure.
_PROMPT_REF = re.compile(r"prompts/([a-zA-Z0-9_-]+)\.md")

_BLOCK = re.compile(re.escape(_BEGIN) + r".*?" + re.escape(_END), re.S)


def frontmatter(text: str) -> dict[str, str]:
    """Parse a command's frontmatter into a flat mapping; empty when there is none."""
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}
    return {key: value.strip() for key, value in _FIELD.findall(match.group(1))}


def _unquote(value: str) -> str:
    """Strip the surrounding quotes an ``argument-hint`` usually carries."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _tools(value: str) -> str:
    """Render an ``allowed-tools`` list as inline code, comma separated."""
    tools = [tool.strip() for tool in value.split(",") if tool.strip()]
    return ", ".join(f"`{tool}`" for tool in tools) if tools else "_none declared_"


def command_block(name: str, meta: dict[str, str]) -> str:
    """The reference table for a slash command."""
    hint = _unquote(meta.get("argument-hint", "")).strip()
    invocation = f"/rhiza:{name} {hint}".strip()
    invocable = (
        "no — excluded from model invocation"
        if meta.get("disable-model-invocation") == "true"
        else "yes"
    )
    rows = [
        ("Source", f"`{COMMANDS_DIR}/{name}.md`"),
        ("Invocation", f"`{invocation}`"),
        ("Model-invocable", invocable),
        ("Allowed tools", _tools(meta.get("allowed-tools", ""))),
    ]
    return _table(rows)


def procedure_block(name: str, readers: list[str]) -> str:
    """The reference table for an internal procedure."""
    if readers:
        read_by = ", ".join(
            f"[`/rhiza:{reader}`](../commands/{reader}.md)"
            if kind == "command"
            else f"[`{reader}`]({reader}.md)"
            for kind, reader in _classify(readers)
        )
    else:
        # check_prompt_wiring.py rule 5 forbids an orphan, so this should be
        # unreachable in this repo — but rendering "nothing" beats rendering an
        # empty cell if that gate is ever loosened.
        read_by = "_nothing — this procedure is an orphan_"
    rows = [
        ("Source", f"`{PROMPTS_DIR}/{name}.md`"),
        ("Invocation", "**not a slash command** — reached with `Read`, never invoked"),
        ("Read by", read_by),
    ]
    return _table(rows)


def _classify(readers: list[str]) -> list[tuple[str, str]]:
    """Tag each reader as a command or a procedure, for link building."""
    return [
        ("command" if kind == "commands" else "procedure", stem)
        for kind, stem in (reader.split("/", 1) for reader in readers)
    ]


def _table(rows: list[tuple[str, str]]) -> str:
    """Render label/value pairs as a headerless two-column markdown table."""
    body = "\n".join(f"| **{label}** | {value} |" for label, value in rows)
    return f"{_BEGIN}\n\n## Reference\n\n| | |\n| --- | --- |\n{body}\n\n{_END}"


def readers_of(name: str, root: Path) -> list[str]:
    """Which commands and procedures reference ``prompts/<name>.md``, sorted."""
    found = set()
    # The returned prefix is the *kind* ("commands"/"prompts"), not the directory —
    # _classify keys off it to build the right relative link, and the directory now
    # carries a `plugin/` segment that has no place in a docs URL.
    for kind, directory in (("commands", COMMANDS_DIR), ("prompts", PROMPTS_DIR)):
        for path in sorted((root / directory).glob("*.md")):
            if path.stem == name:
                continue
            if name in _PROMPT_REF.findall(path.read_text(encoding="utf-8")):
                found.add(f"{kind}/{path.stem}")
    return sorted(found)


def splice(page: str, block: str) -> str:
    """Replace the page's generated block, or append one when it has none."""
    if _BLOCK.search(page):
        return _BLOCK.sub(lambda _: block, page, count=1)
    return f"{page.rstrip()}\n\n{block}\n"


def render(root: Path) -> dict[Path, str]:
    """Map every docs page to the text it should have."""
    wanted: dict[Path, str] = {}
    for source, docs_dir in ((COMMANDS_DIR, "commands"), (PROMPTS_DIR, "internals")):
        for path in sorted((root / source).glob("*.md")):
            page = root / "docs" / docs_dir / f"{path.stem}.md"
            if not page.is_file():
                continue
            block = (
                command_block(path.stem, frontmatter(path.read_text(encoding="utf-8")))
                if source == COMMANDS_DIR
                else procedure_block(path.stem, readers_of(path.stem, root))
            )
            wanted[page] = splice(page.read_text(encoding="utf-8"), block)
    return wanted


def main(argv: list[str] | None = None) -> int:
    """Write or verify every generated block; exit 1 under ``--check`` when stale."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd).")
    parser.add_argument(
        "--check", action="store_true", help="Verify only; write nothing. Exit 1 if stale."
    )
    args = parser.parse_args(argv)

    stale = []
    for page, text in render(Path(args.root)).items():
        if page.read_text(encoding="utf-8") == text:
            continue
        stale.append(page)
        if not args.check:
            page.write_text(text, encoding="utf-8")

    if not stale:
        print("docs reference blocks are up to date")
        return 0
    if args.check:
        print("Stale generated block(s) — run scripts/render_command_docs.py:", file=sys.stderr)
        for page in stale:
            print(f"  ✗ {page}", file=sys.stderr)
        return 1
    for page in stale:
        print(f"  updated {page}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
