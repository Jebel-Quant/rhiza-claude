# `/rhiza:quality`

Run the Rhiza code-quality gate and score the current repo, then optionally file
findings as issues.

```
/rhiza:quality [path or topic to scope the assessment to]
```

The optional argument scopes the assessment; it defaults to the whole repo.

!!! important "Requires a rhiza-managed **and synced** repo"
    `/quality` checks for `.rhiza/template.yml` and `.rhiza/rhiza.mk` before doing
    anything, and stops if either is missing:

    - **no `template.yml`** — the repo isn't rhiza-managed. Scoring it against
      standards it never adopted is a category error, not a low score. Run
      [`/rhiza:init`](init.md).
    - **no `rhiza.mk`** — managed but never synced, which is the state `/init`
      deliberately leaves behind. Run [`/rhiza:update`](update.md) first.

    Every gate is a `make` target the sync delivers, so without them all the gates
    fail with *"No rule to make target"* and the scorecard would report a broken repo
    when the truth is an unsynced one.

## What it does

1. **Runs the quality gates** (cheapest first) — lint, types, docs, deps, security,
   template drift, tests, and test-layout parity. Because the available targets depend
   on the profile in `template.yml` (`typecheck`, `security` and `docs-coverage` come
   from the *tests* bundle), it probes each with `make -n` first; a target that isn't
   in the profile is scored **out-of-scope**, not FAIL.
2. **Gathers design evidence itself** — complexity via `radon cc`/`radon mi`, plus an
   import-graph read for layering direction, cycles (including ones hidden behind
   function-local imports), god-modules and coupling hotspots. No `make` target
   measures these.
3. **Scores 1–10** per subcategory, with an overall score and the single
   highest-leverage improvement called out.
4. **Produces actionable findings** — one per subcategory below 10, each with a
   self-contained title, the current→target score, the specific file(s)/config, a
   `done when…` criterion, and an evidence snippet, ordered by leverage.
5. **Optionally files issues** for them — via a multi-select menu, never free text,
   and nothing created without an explicit selection.

## Language support: the gate list is the Python profile

!!! warning "A Rust or Go scorecard rests on a narrower base"
    The numbered gate list above is the **Python** profile — the one this plugin has
    actually run against. On a Rust or Go repo most of those targets are unavailable,
    so `/quality` probes the Makefile with `check_make_targets.py`, scores the targets
    it **discovers**, and marks language-specific subcategories (test-layout parity
    above all) out-of-scope rather than measuring them.

    That is deliberate — a hand-written table of targets for templates the plugin has
    never run against would be prose asserting things it cannot back, and discovery
    degrades honestly where a guessed table would lie. But it means a Rust or Go score
    is **not comparable** to a Python one, so the command states in its own output which
    gates were discovered and which subcategories were skipped.

    See [Language support](../index.md) for what else differs — notably that neither
    Rust nor Go has hosted CI workflows yet.

## Why gates run through `make`

Invoking the tools directly (`uvx ruff check`, `uvx interrogate`, …) would let
`/quality` run anywhere, but the two **disagree**: measured against this plugin's own
repo, bare `interrogate` reports FAILED at 99.5% where the configured hook passes, and
bare `bandit` reports a high-severity finding where the configured hook passes. The
arguments, thresholds and exclusions live in the `make` target and
`.pre-commit-config.yaml`, so a direct call measures something else — and for a command
whose output is a score and a findings list, that means inventing failures and filing
issues for them.

The `make` target is also the entry point CI uses, which is what makes its verdict the
one worth scoring.

## Notes

- **It assesses; it does not fix.** Failures are diagnosed and a fix proposed, never
  applied — a scoring run that quietly edits code makes its own score unreproducible.
  The only exception is whatever `make fmt` auto-formats as a side effect of running.
- **Respects the locally-owned vs. Rhiza-owned split**, so template-managed files
  (`Makefile`, `.pre-commit-config.yaml`, `ruff.toml`, workflows) don't drive the
  marks — a gap there is flagged upstream, not scored against you.
- **`/quality` is the only command that scores.** [`/rhiza:update`](update.md) used to
  invoke it and carry a scorecard in its PR; it no longer does, so that a template bump
  can't be polluted by `make fmt` rewriting your files. Run this yourself when you want
  a score.
- Don't confuse `make validate` (repo drifted from the template) with
  `scripts/validate.py`, which [`/rhiza:status`](status.md) runs (is `template.yml`
  well-formed). A repo can pass one and fail the other.

<!-- generated:begin — rendered by scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `commands/quality.md` |
| **Invocation** | `/rhiza:quality [path or topic to scope the assessment to]  (optional; defaults to the whole repo)` |
| **Model-invocable** | yes |
| **Allowed tools** | `Bash(make*)`, `Bash(git*)`, `Bash(gh*)`, `Bash(glab*)`, `Bash(uv*)`, `Bash(uvx*)`, `Bash(python3*)`, `Bash(grep*)`, `Bash(find*)`, `Bash(wc*)`, `Bash(sed*)`, `Bash(sort*)`, `Bash(uniq*)`, `Grep`, `Glob`, `Read`, `Edit`, `Write`, `AskUserQuestion` |

<!-- generated:end -->
