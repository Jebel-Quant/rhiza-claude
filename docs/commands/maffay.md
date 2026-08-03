# `/rhiza:maffay`

Return a bonmot from a random Peter Maffay song. A one-liner for the middle of a long
refactor — no repo required, nothing written, nothing scored.

```
/rhiza:maffay [theme keyword e.g. mut]
```

With no argument it draws from the whole catalogue. Pass a theme keyword (`mut`,
`sommer`, `nessaja`, `liebe`, `geduld`, …) or part of a song title to narrow the pool;
matching is case-insensitive substring, so `brücken` finds *Über sieben Brücken musst du
gehn*.

```console
$ /rhiza:maffay nessaja
🎸 „Ich wollte nie erwachsen sein“
   — Peter Maffay, „Nessaja“ (1983)
   Für uns: Curiosity is the feature; seniority is the side effect.
```

## Why a script for a joke

Because a model asked to "pick a random song" doesn't. It reaches for the two or three
best-known titles, so by the third run the command feels broken — the same reason
[`/rhiza:release`](release.md) hands its version arithmetic to a script rather than
deriving it in prose. `plugin/scripts/maffay.py` owns the draw, and `random.choice` over the
catalogue is uniform where prose isn't. A test asserts every entry is reachable, so an
entry that could never be drawn fails the suite rather than quietly never appearing.

`--seed N` makes a draw reproducible (that's how the tests pin it), `--list` prints the
whole catalogue, and `--json` returns the entry as one object.

## What is quoted, and what isn't

Each entry holds the song's **title line** — which for Maffay is nearly always the hook
itself — with song and year attributed. **Lyric bodies are not reproduced.** A title
isn't a protectable work; a verse is, and shipping verses inside a distributed plugin is
redistribution, so the catalogue simply doesn't contain any.

The `Für uns:` line is **this repo's own gloss**, not Maffay's words. The label stays in
the output on purpose: without it the joke reads as a lyric, which is the one confusion
the format exists to prevent.

## Adding a song

One entry appended to `BONMOTS` in `plugin/scripts/maffay.py`:

```python
{
    "line": "Über sieben Brücken musst du gehn",
    "song": "Über sieben Brücken musst du gehn",
    "year": 1980,
    "themes": ("geduld", "weg", "release"),
    "apply": "Seven detours before the fix lands. Ship it anyway.",
}
```

Only add songs whose **title and year you can confirm** — a plausible-looking wrong year
is worse than a shorter catalogue. `themes` must be non-empty (a test enforces it), or
`--theme` could never surface the entry.

## Notes

- **Read-only and repo-free.** No `.rhiza/`, no git, no network — it works in any
  directory, which makes it the one command here that can't fail on a broken repo.
- Needs `uv` only, and the script is stdlib-only.
- *Über sieben Brücken musst du gehn* is a Karat song (1978); the catalogue attributes
  the year of **Maffay's** recording, 1980.

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/commands/maffay.md` |
| **Invocation** | `/rhiza:maffay [theme keyword e.g. mut]  (optional; omit for the whole catalogue)` |
| **Model-invocable** | yes |
| **Allowed tools** | `Bash(uv*)` |

<!-- generated:end -->
