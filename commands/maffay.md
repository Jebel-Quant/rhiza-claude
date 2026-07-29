---
description: Return a bonmot from a random Peter Maffay song — a one-line pick-me-up for a long refactor, backed by the bundled scripts/maffay.py so the choice is actually uniform rather than a model reaching for the same two hits. Quotes the song's title line only, with song and year attributed; lyric bodies are never reproduced, and the "Für uns" gloss beside each line is this repo's own, not Maffay's. Takes an optional theme keyword (e.g. mut, sommer, nessaja) to narrow the pool. Read-only — it touches no files, needs no git, and works in any directory.
argument-hint: "[theme keyword e.g. mut]  (optional; omit for the whole catalogue)"
allowed-tools: Bash(uv*)
---

You are running `/maffay`. Goal: print **one** bonmot from a random Peter Maffay song.

That is the whole command. It reads nothing, writes nothing, and needs no repo — so it
works anywhere, including outside a rhiza-managed project.

**Do not pick the song yourself.** Asked to choose "at random" you will reach for
*Über sieben Brücken* and *Nessaja* almost every time, and by the third run the command
feels broken. The bundled script owns the choice, and `random.choice` over the
catalogue is uniform where you are not. Run it and relay the output verbatim.

Argument (optional): `$ARGUMENTS` — a theme keyword (`mut`, `sommer`, `nessaja`,
`liebe`, …) or part of a song title, matched case-insensitively. Anything else is
still passed through: the script reports the known themes itself on a miss, which is
more useful than you guessing what the user meant.

## 1. Draw one

`${CLAUDE_PLUGIN_ROOT}` resolves at runtime (**keep the quotes**); in a source
checkout it's empty, so fall back to the repo-relative path.

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/maffay.py" --theme "$ARGUMENTS"
```

Drop `--theme` entirely when `$ARGUMENTS` is empty — an empty theme is not the same
as no theme, and passing `--theme ""` matches everything by accident rather than by
intent.

Exit **1** means the theme matched nothing. The script has already printed the known
themes; show that and stop. Do **not** retry without the filter and pass the result
off as what they asked for, and do **not** invent a song to fill the gap.

`--seed N` makes a draw reproducible and `--list` prints the whole catalogue; both are
there for demos and tests. `--json` gives the same entry as one object if you need the
fields.

## 2. Report

Relay the three lines as printed. Two things not to blur:

- **The quoted line is the song's title line** — the hook, and the only quoted text.
  Do not extend it into a verse from memory. A title is not a protectable work; the
  lyric body is, and this command deliberately does not ship one.
- **`Für uns:` is this repo's gloss, not Maffay's words.** Keep the label. If you drop
  it the joke reads as a lyric, which is exactly the confusion the format prevents.

One bonmot per invocation. If the user wants another, run it again.
