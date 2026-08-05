#!/usr/bin/env python3
"""Return a bonmot from a random Peter Maffay song — behind `/rhiza:maffay`.

The point of a bundled script rather than prose is the same as everywhere else in
this plugin: a model asked to "pick a random song" does not pick randomly. It
gravitates to the two or three best-known titles, so the command would feel broken
by the third run. `random.choice` over a curated list actually is uniform, and
`--seed` makes a run reproducible for tests and for a demo.

**What is quoted, and what is not.** Each entry holds the song's *title line* — for
Maffay that is nearly always the hook itself ("Über sieben Brücken musst du gehn",
"Ich wollte nie erwachsen sein") — with the song and year attributed. Lyric bodies
are deliberately **not** reproduced: a title is not a protectable work, a verse is,
and shipping verses inside a plugin is redistribution. The ``apply`` line beside each
entry is this repo's own gloss, not part of the song, and is labelled as such in the
output so the two are never confused.

Adding an entry is a one-line edit to ``BONMOTS``; keep the same shape and only add
songs whose title and year you can actually confirm.

Usage:
  uv run --python 3.12 --no-project python \
      scripts/maffay.py [--theme WORD] [--seed N] [--list] [--json]

Exit codes:
  0  a bonmot was returned (or the catalogue was listed)
  1  --theme matched nothing in the catalogue
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from typing import Any

EXIT_OK = 0
EXIT_NO_MATCH = 1

# line:  the song's title line — the hook, and the only quoted text.
# apply: this repo's gloss, not Maffay's words. Kept short and shipping-related.
BONMOTS: tuple[dict[str, Any], ...] = (
    {
        "line": "Über sieben Brücken musst du gehn",
        "song": "Über sieben Brücken musst du gehn",
        "year": 1980,
        "themes": ("geduld", "weg", "release"),
        "apply": "Seven detours before the fix lands. Ship it anyway.",
    },
    {
        "line": "Und es war Sommer",
        "song": "Und es war Sommer",
        "year": 1976,
        "themes": ("nostalgie", "sommer"),
        "apply": "The commit you remember fondly is the one you no longer have to maintain.",
    },
    {
        "line": "So bist du",
        "song": "So bist du",
        "year": 1979,
        "themes": ("annahme", "liebe"),
        "apply": "Take the codebase as it is first; refactor it second.",
    },
    {
        "line": "Ich wollte nie erwachsen sein",
        "song": "Nessaja",
        "year": 1983,
        "themes": ("neugier", "spiel", "nessaja"),
        "apply": "Curiosity is the feature; seniority is the side effect.",
    },
    {
        "line": "Du",
        "song": "Du",
        "year": 1970,
        "themes": ("liebe", "anfang"),
        "apply": "One word, a whole career. Small diffs travel furthest.",
    },
    {
        "line": "Josie",
        "song": "Josie",
        "year": 1979,
        "themes": ("aufbruch", "abschied"),
        "apply": "Some branches you say goodbye to instead of merging.",
    },
    {
        "line": "Eiszeit",
        "song": "Eiszeit",
        "year": 1982,
        "themes": ("kälte", "warnung"),
        "apply": "A repo with no tests is an ice age with good intentions.",
    },
    {
        "line": "Tabaluga",
        "song": "Tabaluga",
        "year": 1983,
        "themes": ("mut", "nessaja", "spiel"),
        "apply": "A small dragon, a long journey — that is every migration.",
    },
)


def themes() -> list[str]:
    """Return every theme keyword in the catalogue, sorted and deduplicated."""
    return sorted({theme for entry in BONMOTS for theme in entry["themes"]})


def candidates(theme: str | None) -> list[dict[str, Any]]:
    """Return the entries matching *theme* — all of them when *theme* is None.

    Matching is a case-insensitive substring test against the theme keywords and the
    song title, so ``--theme sommer`` and ``--theme Brücken`` both land.
    """
    if theme is None:
        return list(BONMOTS)
    needle = theme.strip().casefold()
    return [
        entry
        for entry in BONMOTS
        if any(needle in t.casefold() for t in entry["themes"])
        or needle in entry["song"].casefold()
    ]


def pick(theme: str | None = None, seed: int | None = None) -> dict[str, Any] | None:
    """Return one random matching entry, or None when *theme* matches nothing."""
    pool = candidates(theme)
    if not pool:
        return None
    # noqa/nosec: picking a Peter Maffay lyric, not a key. `--seed` exists so the tests
    # can pin the choice, which a cryptographic generator would make impossible.
    rng = random.Random(seed)  # noqa: S311  # nosec B311
    return rng.choice(pool)


def render(entry: dict[str, Any]) -> str:
    """Format *entry* for the terminal, keeping the gloss visibly separate."""
    return "\n".join(
        (
            f"🎸 „{entry['line']}“",
            f"   — Peter Maffay, „{entry['song']}“ ({entry['year']})",
            f"   Für uns: {entry['apply']}",
        )
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point: print one bonmot (or the catalogue) and return an exit code."""
    parser = argparse.ArgumentParser(
        description="Return a bonmot from a random Peter Maffay song.",
    )
    parser.add_argument("--theme", help="Only consider songs matching this keyword or title.")
    parser.add_argument("--seed", type=int, help="Seed the choice, for a reproducible run.")
    parser.add_argument(
        "--list", dest="list_all", action="store_true", help="Print the whole catalogue instead."
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the result as JSON."
    )
    args = parser.parse_args(argv)

    if args.list_all:
        pool = candidates(args.theme)
        if args.json_output:
            print(json.dumps({"themes": themes(), "bonmots": pool}, ensure_ascii=False, indent=2))
        else:
            for item in pool:
                print(render(item), end="\n\n")
            print(f"{len(pool)} songs · themes: {', '.join(themes())}")
        return EXIT_OK

    entry = pick(args.theme, args.seed)
    if entry is None:
        print(
            f"error: no song matches --theme {args.theme!r}. Known themes: {', '.join(themes())}",
            file=sys.stderr,
        )
        return EXIT_NO_MATCH

    print(json.dumps(entry, ensure_ascii=False) if args.json_output else render(entry))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
