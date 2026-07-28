---
description: Run the Rhiza code-quality gate and score the current repo (lint, types, docs, deps, security, tests, test-layout, complexity, architecture), then optionally file findings as issues. Requires a rhiza-managed AND synced repo — it checks for .rhiza/template.yml and .rhiza/rhiza.mk first and stops otherwise, since every gate is a make target the sync delivers and an unsynced repo would score as broken rather than unsynced. Assesses only; it proposes fixes but does not apply them.
argument-hint: "[path or topic to scope the assessment to]  (optional; defaults to the whole repo)"
allowed-tools: Bash(make*), Bash(git*), Bash(gh*), Bash(glab*), Bash(uv*), Bash(uvx*), Bash(python3*), Bash(grep*), Bash(find*), Bash(wc*), Bash(sed*), Bash(sort*), Bash(uniq*), Grep, Glob, Read, Edit, Write, AskUserQuestion
---

Assess the quality of the **current working directory's repo** against Rhiza
standards. This is the global variant of the per-repo `rhiza_quality` command
synced from `jebel-quant/rhiza`; it adapts to whichever repo it runs in by
reading that repo's `CLAUDE.md`, `.rhiza/template.lock`, and git remote at
runtime.

## 0. Preconditions — a synced, rhiza-managed repo

**`/quality` only runs in a rhiza-managed repo that has been synced.** These two
checks come **first — before any `make`, any tool, any analysis**:

```bash
test -f .rhiza/template.yml   # rhiza-managed at all?
test -f .rhiza/rhiza.mk       # ...and actually synced?
```

- **No `.rhiza/template.yml` → stop immediately.** The repo isn't rhiza-managed.
  Scoring a repo against Rhiza standards it never adopted is a category error, not a
  low score. Say so plainly and point at `/rhiza:init`. Do not run a single gate, and
  do not produce a partial scorecard.
- **No `.rhiza/rhiza.mk` → stop.** Managed but never synced — the state `/init`
  leaves behind, since it deliberately doesn't sync. Point at `/rhiza:update`, which
  performs the first sync.

Why this is a hard precondition rather than a graceful degradation: **every gate
below is a `make` target that the sync delivers.** Without `.rhiza/rhiza.mk` all of
them fail with "No rule to make target", and the scorecard would report a broken
repo when the truth is an unsynced one. A misleading score is worse than no score.

**Profiles vary, so probe before running.** `typecheck`, `security` and
`docs-coverage` come from the *tests* bundle and `deptry`/`fmt` from *core*, so the
available set depends on the profile in `template.yml`. Check each target cheaply
with `make -n <target>` first. A target that isn't defined is **"unavailable
(not in this profile)"** — score that subcategory **out-of-scope**, exactly like the
Rhiza-owned rule below. Never score it FAIL.

## 1. Run the gates

Follow the command-execution policy: always prefer `make <target>`; never invoke
`.venv/bin/...` directly. Run them in order — cheapest checks first so fast failures
surface before the slow test suite — and collect results:

1. `make fmt` — pre-commit hooks + linting (ruff format/check, markdownlint, bandit, actionlint, …)
2. `make typecheck` — static type checking (`ty`, and `mypy --strict` if configured) over `src/`
3. `make docs-coverage` — docstring coverage (interrogate) over `src/`
4. `make deptry` — unused/missing/misplaced dependency analysis
5. `make security` — pip-audit + bandit scans
6. `make validate` — validate project structure against the Rhiza template (`.rhiza/template.yml`)
7. `make test` — full test suite **with** its coverage gate (slowest, run last)
8. **Test-layout parity** — run the bundled checker
   `uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/check_test_layout.py"` (fall back to
   `uv run --python 3.12 --no-project python scripts/check_test_layout.py` in a source checkout). It fails when a
   source module has no mirrored `test_<name>.py`, a source `class A` has no
   `TestA`, or a test file/`Test*` class has no source counterpart. A repo that
   deliberately organises tests by behaviour (and guarantees per-module
   coverage another way, e.g. a 100% coverage gate) can opt out with a
   documented `[tool.check_test_layout]` table in `pyproject.toml`
   (`enforce = false` + a required `reason`); score this subcategory 10 when the
   checker exits 0, whether by mirroring or a documented opt-out.

**Why `make` and not the tools directly.** It's tempting to replace these with
`uvx ruff check`, `uvx interrogate`, `uvx bandit` and so on, which would let
`/quality` run anywhere. **Don't** — the two disagree, and measured against this very
repo they disagree in the worst direction: `interrogate` run bare reports FAILED at
99.5% where the configured hook passes, and `bandit` run bare reports a high-severity
finding where the configured hook passes. The arguments, thresholds and exclusions
live in the `make` target (and in `.pre-commit-config.yaml`), so a direct invocation
measures something else. For a command whose entire output is a score and a findings
list, that means inventing failures — and then filing issues for them. The `make`
target is the same entry point CI uses, which is exactly why its verdict is the one
worth scoring.

Guidelines:

- Run each gate as a single, bare `make <target>` command — one Bash call per
  gate. Do **not** pipe (`| tee`, `| tail`), redirect (`2>&1 >`), chain
  (`make fmt && make typecheck`), or prefix with `cd`. This is a tooling
  constraint, not methodology: bare invocations match the allow-listed
  `Bash(make *)` rule and run without a permission prompt, while compound or piped
  commands prompt on *every* gate. Read the output directly from each call rather
  than capturing it to a file.
- Run all available gates even after an early failure, so the full picture is
  visible rather than stopping at the first red.
- If something fails, show the relevant output and diagnose the root cause.
  **Propose the fix; don't apply it** — this command assesses, and a scoring run
  that quietly edits code makes its own score unreproducible. The exception is
  whatever `make fmt` auto-formats as part of running, which is unavoidable.
- If `$ARGUMENTS` is non-empty, scope the assessment to that path or topic
  instead of the whole repo.
- End with a concise PASS/FAIL summary per gate.

**Coverage expectation.** `make test` enforces a coverage gate
(`COVERAGE_FAIL_UNDER`, default 90%; many projects raise it to 100%). Treat
anything below the configured threshold on locally-owned `src/` as a gap to
flag, not an acceptable baseline. When scoring the test-coverage subcategory,
the configured threshold is the bar for a 10; report uncovered lines
(`file:line`) and the test that would close each.

**`make validate`.** A failure means this repo has drifted from the Rhiza
template (a synced file edited locally, or a missing/extra file). That is
in-scope: fix it by re-syncing from Rhiza or by adjusting `.rhiza/template.yml`,
not by editing the synced artifact in place.

> Not to be confused with `scripts/validate.py`, which `/rhiza:status` runs. Same
> word, different checks: `make validate` compares the repo against the template
> (drift); `scripts/validate.py` checks that `template.yml` itself is well-formed.
> A repo can pass one and fail the other.

**Design analysis (not a `make` gate — gather the evidence yourself, then score).**
Complexity and architecture are not measured by any gate, so collect the evidence
directly, scoped to locally-owned `src/` (skip Rhiza-managed files per the scoping
rule below):

- **Complexity.** Run `uvx radon cc src -a -s` (per-block cyclomatic complexity +
  average) and `uvx radon mi src -s` (maintainability index). Report every block
  ranking **C or worse (CC ≥ 11)** as `file:line`, any module below **A** on the
  maintainability index, and oversized modules
  (`find src -name '*.py' | xargs wc -l | sort -rn`). If radon is unavailable, fall
  back to reading the largest modules and estimating by inspection — and say so.
- **Architecture.** Map the import graph and verify **layering direction**: a lower
  layer (e.g. `models/`) must not import an upper layer (e.g. `commands/`, `cli`).
  Hunt for **import cycles — including ones hidden behind deferred (function-local)
  imports**; god-modules imported by many; misplaced responsibilities (application/
  orchestration logic living in a model or utility layer); and the composition
  pattern in use (mixins, Protocols, dependency injection). Note coupling hotspots
  (a module imported by many, or one importing many).
- **Other criteria (see the subcategory list below).** Sample the code for each and
  score only those with enough signal to justify a mark; name the evidence you read.

Then report:

- A pass/fail summary per step.
- Failures grouped by file, with the specific rule/error and line.
- A prioritized list of what to fix first (blocking errors before style nits).

Then analyse the repo and give marks on a scale of 1 to 10 for all relevant
subcategories. **Always include Code complexity and Overall architecture**, scored
from the design-analysis evidence above. Then add the gate-derived and additional
subcategories that fit what you actually observe:

- **Gate-derived:** linting/style, type safety, docstring/API-doc coverage, test
  pass rate, test coverage & depth, dependency & security hygiene, template
  fidelity (`make validate` drift).
- **Design (always score both):** *code complexity* — cyclomatic complexity
  (average + the worst C-or-worse blocks), maintainability index, and the size of
  the largest functions/modules; *overall architecture* — layering & dependency
  direction, coupling/cohesion, module responsibility, composition pattern, and the
  absence of import cycles.
- **Additional (score those with signal):** *test design quality* — do tests assert
  behaviour or mirror the implementation? mock depth/brittleness (a brittle suite
  can hit 100% coverage yet pin internals); *error handling & CLI UX* — exit codes,
  actionable messages, failure modes; *security posture & trust boundaries* — input
  validation of `template.yml`/config, path-traversal in any path remapping,
  `subprocess` usage; *public API / semver discipline* — stability of the CLI
  surface and exported models; *cross-platform robustness* — Windows path/symlink
  behaviour; *idempotency & failure recovery* — repeat-run safety, partial-failure
  cleanup; *user-facing documentation* — README/usage, not just docstrings.

For each subcategory: the score, a one-line justification grounded in the evidence
above (gate output, radon metrics, the import graph, or a targeted code read), and
what would raise it. Close with an overall score and the single highest-leverage
improvement.

**Scope the scorecard to locally-owned items — not what the mother repo (Rhiza)
owns.** This project syncs its dev infrastructure from `jebel-quant/rhiza`; see
`CLAUDE.md` for the authoritative split and the `files:` block of
`.rhiza/template.lock` for the machine-generated list of synced files. Score
only what this repo actually controls — `src/`, `tests/`, `pyproject.toml`,
`README.md`, project-specific docs, `.rhiza/template.yml`, and any
locally-hardened config. Do **not** let Rhiza-managed files (the
`.github/workflows/*`, `Makefile`, `.pre-commit-config.yaml`, `pytest.ini`,
`ruff.toml`, the typecheck/mutation/fuzzing targets, etc.) drive the marks — a
gap there is fixed upstream in Rhiza, not here. If a relevant signal is
Rhiza-owned, note it as "upstream/out-of-scope" rather than scoring it against
this repo.

Then, from the scorecard above, identify **actionable issues to improve the
score** — one per subcategory scoring below 10 (skip any that are maxed). For
each, give: a concrete title, the subcategory and current→target score it moves,
the specific file(s)/lines or config to change, and a crisp acceptance criterion
("done when…"). Keep them in-scope (locally-owned, per the scoping rule above) —
flag anything Rhiza-owned as upstream rather than listing it as a local action.
Order them by leverage (biggest score gain for least effort first). This is a
list of recommendations only — do not change code unless I explicitly ask.

Then offer to file the findings as issues — using a menu, not a free-text prompt.
Present the actionable findings as a multi-select menu (the AskUserQuestion tool
with `multiSelect: true`), one option per finding labelled by its title, so I can
pick exactly which ones to file — including none. Create nothing without an
explicit selection. For each finding I select, detect the hosting platform from
the git remote (`git remote get-url origin`) and create one issue with the
matching CLI — GitHub → `gh issue create`, GitLab → `glab issue create` (skip and
say so if the relevant CLI is unavailable or unauthenticated). Make each issue
self-contained: title from the finding, and a body carrying the subcategory, the
current→target score, the specific file(s)/lines or config to change, and the
"done when…" acceptance criterion. Report back the created issue URLs.

> **`/quality` is the only command that scores.** `/update` used to invoke it and
> carry a scorecard in its PR; it no longer does — it syncs the template and nothing
> else, so that a template bump PR can't be polluted by `make fmt` rewriting the
> repo's own files. Run `/quality` yourself, whenever you want a score. Nothing
> invokes this command on your behalf, so there is no assessment-only mode to
> switch into.

If everything passes, say so plainly — but still produce the 1–10 subcategory
marks. Do not fix anything unless I ask — this command only assesses.
