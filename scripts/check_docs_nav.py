#!/usr/bin/env python3
"""Check that every command and procedure has a docs page, wired into the nav.

``CONTRIBUTING.md`` has always required it — "give the command a page under
``docs/commands/<name>.md`` and add it to the ``nav`` in ``mkdocs.yml``" — and nothing
checked it. That left the one documented rule in the contributing guide with no
enforcement behind it, in a repo whose stated position is that prose is gated exactly
like code.

``mkdocs build --strict`` is not the same check. It fails on a nav entry pointing at a
*missing page*, which is the rarer direction. What it cannot see is the likelier one: a
new command whose page was never written, or a page that exists but was never added to
the nav and so ships as an orphan the site never links to.

The four rules, checked in both directions:

1. **Page exists** — every ``commands/<name>.md`` has ``docs/commands/<name>.md``, and
   every ``prompts/<name>.md`` has ``docs/internals/<name>.md``.
2. **Page is navigable** — each of those pages appears in ``mkdocs.yml``'s ``nav``.
3. **No orphan page** — nothing under ``docs/commands/`` or ``docs/internals/`` without
   a backing command or procedure. A page for a command that was renamed or retired
   goes on serving stale instructions long after the command stopped existing.
4. **No dangling nav entry** — every ``nav`` target that names a file under those two
   directories resolves.

The ``nav`` is read by collecting ``*.md`` targets out of the block rather than by
parsing YAML. The bundled subset parser in ``_rhiza_yaml.py`` was written for the flat
shape of ``template.yml`` and ``template.lock``; a mkdocs ``nav`` is a list of nested
single-key mappings, which is exactly the shape it does not promise to handle. For a
parity check the set of referenced paths is the whole question, so extracting it
directly is both sufficient and harder to get wrong.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/check_docs_nav.py [--root DIR]

Exits 0 when every page is present and wired up, 1 (listing each violation) otherwise.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# source directory -> the docs directory whose pages mirror it
_MIRRORS = (("commands", "docs/commands"), ("prompts", "docs/internals"))
# A top-level `nav:` key, and the next top-level key that ends the block.
_NAV_START = re.compile(r"^nav:\s*$", re.M)
_TOP_LEVEL_KEY = re.compile(r"^[A-Za-z_]", re.M)
# Any `*.md` target inside the nav, quoted or bare.
_MD_TARGET = re.compile(r"[\w./-]+\.md")


def nav_targets(mkdocs: Path) -> set[str]:
    """Return every ``*.md`` path referenced in *mkdocs*'s ``nav`` block.

    A missing file, or one with no ``nav:`` key, yields an empty set — the caller
    reports that as every page being unwired rather than as a crash.
    """
    if not mkdocs.is_file():
        return set()
    text = mkdocs.read_text()
    start = _NAV_START.search(text)
    if start is None:
        return set()
    rest = text[start.end() :]
    end = _TOP_LEVEL_KEY.search(rest)
    block = rest[: end.start()] if end else rest
    return set(_MD_TARGET.findall(block))


def _stems(directory: Path) -> set[str]:
    """Return the stems of the markdown files directly in *directory*."""
    if not directory.is_dir():
        return set()
    return {path.stem for path in directory.glob("*.md")}


def check_mirror(root: Path, source: str, docs: str, targets: set[str]) -> list[str]:
    """Apply all four rules to one source/docs directory pair."""
    violations = []
    source_stems = _stems(root / source)
    page_stems = _stems(root / docs)

    for stem in sorted(source_stems - page_stems):
        violations.append(f"{source}/{stem}.md has no page at {docs}/{stem}.md")
    for stem in sorted(page_stems - source_stems):
        violations.append(f"{docs}/{stem}.md has no matching {source}/{stem}.md — orphan page")

    # The nav is written relative to docs/, so `docs/commands/x.md` appears as
    # `commands/x.md`. Accept the full path too, so a repo that spells it out isn't
    # reported as unwired for a cosmetic difference.
    relative = docs.removeprefix("docs/")
    for stem in sorted(source_stems & page_stems):
        if not {f"{relative}/{stem}.md", f"{docs}/{stem}.md"} & targets:
            violations.append(f"{docs}/{stem}.md exists but is not in mkdocs.yml's nav")

    for target in sorted(t for t in targets if t.startswith(f"{relative}/")):
        if not (root / "docs" / target).is_file():
            violations.append(f"mkdocs.yml nav points at docs/{target}, which does not exist")
    return violations


def check_docs_nav(root: Path) -> list[str]:
    """Run the rules over both mirrors at *root*; return all violations."""
    targets = nav_targets(root / "mkdocs.yml")
    violations: list[str] = []
    for source, docs in _MIRRORS:
        violations += check_mirror(root, source, docs, targets)
    return violations


def main(argv: list[str] | None = None) -> int:
    """Entry point: check docs/nav parity and return an exit code."""
    parser = argparse.ArgumentParser(description="Check command/procedure docs and nav parity.")
    parser.add_argument("--root", default=".", help="Plugin root (default: current directory).")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    violations = check_docs_nav(root)
    if violations:
        print("Docs/nav parity check failed:", file=sys.stderr)
        for violation in violations:
            print(f"  ✗ {violation}", file=sys.stderr)
        return 1

    pages = sum(len(_stems(root / docs)) for _, docs in _MIRRORS)
    print(f"docs and nav are in parity ({pages} page(s) checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
