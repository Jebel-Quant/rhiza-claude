#!/usr/bin/env python3
"""Check that counted claims in the prose still match the tree.

Every prose surface in this repo is gated except one. ``check_docs_nav.py`` covers
``docs/``, ``check_command_contracts.py`` covers the commands, ``check_prompt_wiring.py``
covers the procedures, and ``check_doc_examples.py`` covers the README's fences and the
docstrings. ``paper/`` has nothing — and it is the surface ``.bumpversion.toml`` stamps
with the release number, in five places, one of which reads "Every claim here is true of
release vX.Y.Z". An unchecked claim there is not merely stale; each release re-asserts it.

It had already happened twice when this was written. The paper said "nine user-facing
commands" and omitted ``/rhiza:completions`` from its table for the whole of v0.10.0. And
``Makefile`` described "the nine workflows holding write permissions" against a tree
holding ten — which read as true again only because one was later deleted, not because
anyone noticed. Both are the same kind of claim, and it is the kind worth gating: **a
count of files that exist.** That is not a matter of judgement, and the tree is the
authority.

============  =====================================
subject       counted from
============  =====================================
commands      ``_rhiza_layout.command_files(root)``
procedures    ``prompts/*.md``
workflows     ``.github/workflows/*.y{a,}ml``
============  =====================================

**A claim is marked, never guessed at.** The obvious design — read every number followed
by one of those nouns — was written first and thrown away, because English does not
cooperate: "``pr-base`` is read by three commands" and "the two commands that change a
shared repository" are both correct, both counted, and neither is a total. Nothing in the
grammar separates them from "ten slash commands"; only the author knows which is which. A
gate that fails the build on correct prose is worse than no gate, because it gets
disabled.

So the author says so, with a marker on its own line, in whatever comment syntax the file
speaks::

    <!-- rhiza-count: commands -->    a Markdown file
    % rhiza-count: commands           the paper
    # rhiza-count: workflows          the Makefile

The number itself stays in the prose and is stated **once** — the marker carries no count
of its own to drift. Every subject named must then appear as a counted claim in the three
lines that follow, so a marker left behind by a rewritten sentence fails too. One marker
may name several subjects (``rhiza-count: commands procedures``) when one sentence carries
several claims, which the paper's honest-scope line does.

The cost of this design is honest and worth stating: **an unmarked claim is unchecked.**
The gate covers what the author asserted, not everything a reader might read as an
assertion. That is the trade for never being wrong about a sentence.

**"skills" counts commands**, because that is what the paper calls them when describing
the directory. The two are the same set by construction — the directory *is* the command.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/check_prose_counts.py [--root DIR]

Exits 0 when every marked claim matches, 1 (listing each violation) otherwise.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _rhiza_layout import PROMPTS_DIR, command_files

WORKFLOWS_DIR = ".github/workflows"
"""Where the workflows live, relative to the repository root."""

SCANNED = ("paper/*.tex", "Makefile", "README.md", "CLAUDE.md", "docs/*.md", "docs/*/*.md")
"""The prose this gate reads, as globs relative to the repository root.

Build outputs are absent by construction rather than by exclusion: ``docs/paper/`` holds a
PDF and ``docs/reports/`` holds HTML and XML, so neither is reachable through a ``*.md``
glob.
"""

WINDOW = 3
"""How many lines after a marker the claim it announces may appear in.

Three rather than one because the paper wraps at 90 columns, so a claim is routinely split
across a line break — the first stale count found here read "of the ten\\nskills under".
"""

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}

_NOUNS = {
    "commands": "commands",
    "skills": "commands",
    "procedures": "procedures",
    "workflows": "workflows",
}

SUBJECTS = sorted(set(_NOUNS.values()))
"""The subjects a marker may name."""

# `rhiza-count:` in any comment syntax — the leading `%`, `#` or `<!--` is not matched at
# all, so a new file type needs no change here.
_MARKER = re.compile(r"rhiza-count:\s*(?P<subjects>[a-z][a-z ]*)")

# A number, then at most two intervening words, then a noun. `\s+` spans newlines because
# the window is searched as joined text, and IGNORECASE because a claim opening a sentence
# is capitalised — "Eight user-facing commands ship" is the same claim as "eight".
#
# The filler is **lazy**. Greedy, it reaches past the nearer noun to a further one: in
# "two commands, one procedures" the match starting at "two" consumed `commands` and `one`
# as filler and reported two *procedures*, hiding both real claims behind one wrong span.
_CLAIM = re.compile(
    r"\b(?P<count>" + "|".join(_NUMBER_WORDS) + r"|\d+)"
    r"(?:\s+[A-Za-z][\w-]*){0,2}?"
    r"\s+(?P<noun>" + "|".join(_NOUNS) + r")\b",
    re.IGNORECASE,
)


def parse_count(token: str) -> int:
    """Read *token* as a number, written either as a word or as digits.

    >>> parse_count("nine")
    9
    >>> parse_count("Eight")
    8
    >>> parse_count("12")
    12
    """
    word = token.lower()
    return _NUMBER_WORDS[word] if word in _NUMBER_WORDS else int(word)


def marked_subjects(line: str) -> list[str]:
    """The subjects a ``rhiza-count:`` marker on *line* names, or ``[]`` if it has none.

    >>> marked_subjects("% rhiza-count: commands procedures")
    ['commands', 'procedures']
    >>> marked_subjects("just prose about commands")
    []

    An unknown subject is returned as written, so the caller can report it rather than
    silently ignoring a marker that will never match anything:

    >>> marked_subjects("<!-- rhiza-count: sprockets -->")
    ['sprockets']
    """
    match = _MARKER.search(line)
    return match["subjects"].split() if match else []


def unmark(text: str) -> str:
    """Replace every non-alphanumeric character in *text* with a space.

    Markup sits between a number and its noun often enough to matter: the README writes
    "eight ``**internal procedures**``" and the paper writes
    ``\\textbf{slash commands}``. Matching around each syntax in turn is how a regex grows
    a dialect per file type, so the window is flattened to words first.

    Newlines survive, because they are what a reported line number is counted from — and
    ``\\s+`` spans them anyway, so a claim split across a line break still matches:

    >>> unmark("eight **internal procedures**")
    'eight   internal procedures  '
    >>> unmark("of the ten\\nskills")
    'of the ten\\nskills'
    """
    return re.sub(r"[^0-9A-Za-z\n]", " ", text)


def claimed(text: str, subject: str) -> tuple[int, int] | None:
    """What *text* claims for *subject*, as ``(count, line offset)``.

    The offset is counted from the start of *text* and points at the **number**, not at
    the marker that announced it — a claim may sit up to `WINDOW` lines away, and the line
    worth reporting is the one an editor has to change.

    >>> claimed("ten user-facing commands, eight internal procedures", "procedures")
    (8, 0)
    >>> claimed("a catalogue of the ten\\nskills under skills/", "commands")
    (10, 0)
    >>> claimed("marker\\nholds eight **internal procedures**", "procedures")
    (8, 1)
    >>> claimed("nothing counted here", "workflows") is None
    True
    """
    flattened = unmark(text)
    for match in _CLAIM.finditer(flattened):
        if _NOUNS[match["noun"].lower()] == subject:
            return parse_count(match["count"]), flattened.count("\n", 0, match.start())
    return None


def tally(root: Path) -> dict[str, int]:
    """Count what the tree at *root* actually holds, per subject."""
    workflows = (root / WORKFLOWS_DIR).glob("*.yml"), (root / WORKFLOWS_DIR).glob("*.yaml")
    return {
        "commands": len(command_files(root)),
        "procedures": len(list((root / PROMPTS_DIR).glob("*.md"))),
        "workflows": sum(len(list(found)) for found in workflows),
    }


def scanned_files(root: Path) -> list[Path]:
    """Every prose file under *root* this gate reads, sorted and deduplicated."""
    found = {path for glob in SCANNED for path in root.glob(glob) if path.is_file()}
    return sorted(found)


def check_file(relative: str, text: str, actual: dict[str, int]) -> tuple[list[str], int]:
    """Check every marked claim in *text*; return the violations and how many ran."""
    violations: list[str] = []
    checked = 0
    lines = text.splitlines()
    for index, line in enumerate(lines):
        for subject in marked_subjects(line):
            where = f"{relative}:{index + 1}"
            if subject not in actual:
                violations.append(
                    f"{where} marks `{subject}`, which is not a counted subject "
                    f"({', '.join(SUBJECTS)})"
                )
                continue
            checked += 1
            # The marker's own line is part of the window, so a marker may sit inline with
            # the claim as well as above it. A table row cannot carry a comment line
            # between it and the row before without ending the table.
            window = "\n".join(lines[index : index + 1 + WINDOW])
            found = claimed(window, subject)
            if found is None:
                violations.append(
                    f"{where} marks `{subject}` but no claim about {subject} follows it "
                    f"within {WINDOW} line(s)"
                )
            elif found[0] != actual[subject]:
                violations.append(
                    f"{relative}:{index + 1 + found[1]} claims {found[0]} {subject}, "
                    f"but the tree holds {actual[subject]}"
                )
    return violations, checked


def check_prose_counts(root: Path) -> tuple[list[str], int]:
    """Check every marked claim under *root*; return the violations and how many ran."""
    actual = tally(root)
    violations: list[str] = []
    checked = 0
    for path in scanned_files(root):
        found, ran = check_file(
            path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"), actual
        )
        violations += found
        checked += ran
    return violations, checked


def main(argv: list[str] | None = None) -> int:
    """Entry point: check the prose's counted claims and return an exit code."""
    parser = argparse.ArgumentParser(description="Check counted claims in the prose.")
    parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    violations, checked = check_prose_counts(root)
    if violations:
        print("Prose count check failed:", file=sys.stderr)
        for violation in violations:
            print(f"  ✗ {violation}", file=sys.stderr)
        return 1

    print(f"prose counts match the tree ({checked} marked claim(s) checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
