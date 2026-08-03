# design-analysis (internal)

Gather the complexity and architecture evidence that **no `make` gate measures**.

!!! note "Not a slash command"
    This is an **internal procedure** (`plugin/prompts/design-analysis.md`), not something you
    invoke. [`/rhiza:quality`](../commands/quality.md) reads and follows it after the
    gates have run.

## Why it exists

`/quality` must *always* score two subcategories — code complexity and overall
architecture — and neither is produced by any gate. Every other input to the scorecard
comes from a `make` target; this evidence is gathered by hand, or the two marks are
guesses.

## What it does

1. **Complexity** — `radon cc src -a -s` and `radon mi src -s`, plus module line counts.
   Reports every block at **C or worse (CC ≥ 11)** as `file:line`, modules below **A**
   on the maintainability index, and the largest modules and functions. If `radon` is
   unavailable it estimates by inspection **and says so** — an estimate presented as a
   measurement is worse than no number.
2. **Architecture** — maps the import graph and checks layering direction (a lower layer
   must not import an upper one), **import cycles including ones hidden behind
   function-local imports**, module responsibility and god-modules, and coupling
   hotspots plus the composition pattern in use.
3. **The other judgement-based criteria** — samples the code for each subcategory that
   no gate measures, scoring only those with enough signal and naming the evidence read.

## Notes

- **Scope is locally-owned `src/`.** A synced file's complexity is upstream's problem —
  see the scoping rule in [scorecard](scorecard.md).
- **It gathers; it doesn't judge.** Marks are [scorecard](scorecard.md)'s job.
- The function-local import cycle is the finding that matters most in practice: a
  module-level cycle usually crashes and gets fixed, while a deferred one survives for
  years.

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/prompts/design-analysis.md` |
| **Invocation** | **not a slash command** — reached with `Read`, never invoked |
| **Read by** | [`/rhiza:quality`](../commands/quality.md), [`scorecard`](scorecard.md) |

<!-- generated:end -->
