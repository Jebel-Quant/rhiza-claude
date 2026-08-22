# `/rhiza:quality`

Run the Rhiza code-quality gate and score the current repo, then optionally file
findings as issues.

```
/rhiza:quality [path or topic to scope the assessment to]
```

The optional argument scopes the assessment; it defaults to the whole repo.

!!! important "Three modes, decided by what `.rhiza/` holds"
    `/quality` checks for `.rhiza/template.yml`, `.rhiza/template.lock` and
    `.rhiza/template-bundles.yml` before doing anything, and adapts rather than refusing:

    - **pointer + lock** — *full mode*: the template's gates plus the design assessment.
    - **`template.yml` only** — *degraded mode*: managed but never synced, the state
      [`/rhiza:init`](init.md) deliberately leaves behind.
      [`/rhiza:update`](update.md) performs the first sync.
    - **`template-bundles.yml`, no pointer** — *template mode*: this repo **is** the
      template. See below.
    - **none of them** — *degraded mode*: the repo isn't rhiza-managed.

    In degraded mode it skips every template-delivered gate, runs whatever targets your
    own `Makefile` provides, and scores the design work in full.

    What it will **not** do is run the template's gates anyway. Every one is a gate the
    sync delivers, so in an unsynced repo they all fail with *"No rule to make target"*
    — and reporting that as FAIL would describe a broken repo when the truth is an
    unsynced one. Skipped gates are scored out-of-scope, never failures, and the report
    names which mode produced the number.

    The second probe is the **lock**, deliberately: it is written by every sync at every
    template version, where a synced *file* is only ever a proxy for one. That proxy was
    `.rhiza/rhiza.mk` until template v1.4 retired the make layer and stopped shipping it
    — after which every correctly and fully synced v1.4 repo answered "never synced" and
    was quietly scored in the narrower mode.

!!! note "Template mode — running `/quality` on the template repository"
    `jebel-quant/rhiza` has no pointer and no lock, because nothing is above it. Read
    naively that is "not rhiza-managed", and the command would offer `/rhiza:init` to the
    repository that ships the bundles `/init` points at. `.rhiza/template-bundles.yml` —
    the bundle-and-profile manifest a sync reads *out of* the template — is what says
    otherwise.

    It runs like degraded mode, with the messaging corrected: no `/rhiza:init` or
    `/rhiza:update` suggestion, no "no Rhiza gate ran" boilerplate (the gates that ran
    are the ones every managed repo receives), and the infrastructure assessment is the
    *main* result rather than a fallback — those files are what consumers inherit. The
    "fix it upstream" escape hatch is gone too: in this repo, upstream is here.

## What it does

1. **Runs the quality gates** (cheapest first) — lint, types, docs, deps, security,
   template drift, tests, test-layout parity, and the executable-documentation check.
   Because the available targets depend
   on the profile in `template.yml` (`typecheck`, `security` and `docs-coverage` come
   from the *tests* bundle), it probes each with `make -n` first; a target that isn't
   in the profile is scored **out-of-scope**, not FAIL.

    **Four gates are the exception — `fmt`, `typecheck`, `docs-coverage` and `deps`
    resolve in any repo**, because they are gated in most mature repos and reporting them
    unavailable understates coverage. Each tries its `make` target, then falls back to
    *your own* tool config: `.pre-commit-config.yaml` through its own runner,
    `[tool.mypy]`, `[tool.interrogate]`, `[tool.deptry]`. Every threshold still comes from
    your committed config — which is the thing that matters — and only the path is passed.

    **No config means out-of-scope, never the template's flags.** Copying `mypy --strict`
    onto a repo that never chose it measures a standard the repo didn't adopt and then
    files issues for it. Declining to gate something is a process finding, not a failure.

    A target merely *named* `lint` or `format` is deliberately not accepted as a stand-in
    either: the name doesn't tell you the scope. This repo's `make lint` also runs mypy,
    interrogate and the contract checkers, so scoring it as `fmt` would credit formatting
    with most of the toolchain.
    **Documentation is checked for truth, not just presence.** `plugin/scripts/check_doc_examples.py`
    runs alongside the gates in any repo: it finds the `>>>` examples in your docstrings
    and checks every fenced block in `README.md` — shell parses under `bash -n`, Python
    under `compile()`, and a `python` fence is diffed against the ```result``` block that
    follows it. `--run` additionally *executes* the examples, which imports your modules,
    so it is opt-in; shell fences are never executed at all.

    These are the same three checks a rhiza-managed repo already gets from
    `make rhiza-test` (`.rhiza/tests/test_docstrings.py`, `test_readme.py`,
    `test_readme_validation.py`), on the same `+RHIZA_SKIP` fence flag — so in full mode
    it adds an inventory rather than a second score, and in degraded mode it is the only
    thing asking whether your documented examples still work. A module it cannot import
    is reported **unmeasured**, never failed, and *no examples at all* is reported as a
    gap rather than a pass.
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
  `plugin/scripts/validate.py`, which [`/rhiza:status`](status.md) runs (is `template.yml`
  well-formed). A repo can pass one and fail the other.

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/skills/quality/SKILL.md` |
| **Invocation** | `/rhiza:quality [path or topic to scope the assessment to]  (optional; defaults to the whole repo)` |
| **Model-invocable** | yes |
| **Allowed tools** | `Bash(make*)`, `Bash(git*)`, `Bash(gh*)`, `Bash(glab*)`, `Bash(uv*)`, `Bash(uvx*)`, `Bash(python3*)`, `Bash(grep*)`, `Bash(find*)`, `Bash(wc*)`, `Bash(sed*)`, `Bash(sort*)`, `Bash(uniq*)`, `Grep`, `Glob`, `Read`, `Edit`, `Write`, `AskUserQuestion` |

<!-- generated:end -->
