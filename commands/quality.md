---
description: Run the Rhiza code-quality gate and score the current repo (lint, types, docs, deps, security, tests, test-layout, complexity, architecture), then optionally file findings as issues. Delegates the two judgement-heavy halves to internal procedures — prompts/design-analysis.md gathers the complexity and architecture evidence no make gate measures, and prompts/scorecard.md owns the scoping rule, subcategory list, findings format and issue menu. Requires a rhiza-managed AND synced repo — it checks for .rhiza/template.yml and .rhiza/rhiza.mk first and stops otherwise, since every gate is a make target the sync delivers and an unsynced repo would score as broken rather than unsynced. Assesses only; it proposes fixes but does not apply them.
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

**Profiles vary, so probe before running** (**keep the quotes**; in a source checkout
fall back to the repo-relative path):
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/check_make_targets.py"
```
It reads the gate list **out of this file's numbered list below** — so the probe can
never drift from what you're about to run — and reports each target as `available` or
`unavailable`, using `make -n` so no recipe executes.

`typecheck`, `security` and `docs-coverage` come from the template's *tests* bundle and
`deptry`/`fmt` from *core*, so a reduced profile legitimately lacks some. **Run only the
available gates.** An unavailable one is scored **out-of-scope**, exactly like the
Rhiza-owned rule below — never FAIL. Exit **1** means no makefile at all, which the
preconditions above should already have caught.

## 1. Run the gates

Follow the command-execution policy: always prefer `make <target>`; never invoke
`.venv/bin/...` directly. Run them in order — cheapest checks first so fast failures
surface before the slow test suite — and collect results:

1. `make fmt` — pre-commit hooks + linting (ruff format/check, markdownlint, bandit, actionlint, …)
2. `make typecheck` — static type checking (`ty`, and `mypy --strict` if configured) over `src/`
3. `make docs-coverage` — docstring coverage (interrogate) over `src/`
4. `make deptry` — unused/missing/misplaced dependency analysis
5. `make security` — pip-audit + bandit scans
6. `make rhiza-test` — run the template's own bundled tests under `.rhiza/tests/` (pyproject structure, docstrings, README)
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

**`make rhiza-test`.** Runs the test-suite the template syncs into `.rhiza/tests/` —
the `[project]` structure gate, docstring coverage, README validation. A failure there
is usually a *local* gap the template is checking for, so it is in scope; a failure in
the synced test files themselves is upstream.

> **Known upstream failure: `test_license_classifier_present`.** Through template
> v1.2.1 this asserts a `License :: OSI Approved :: …` trove classifier. PEP 639
> superseded those with the SPDX `license` field that `/rhiza:license` writes, and the
> two are not merely redundant — declaring both makes `setuptools>=77` refuse to build
> the project ("License classifiers have been superseded by license expressions …
> Please remove"), and `uv_build` warns. The gate is therefore unsatisfiable for a
> PEP 639 project. Score it **out-of-scope**, not FAIL, and do not "fix" it by adding
> the classifier — that trades a failing gate for an unbuildable package. Filed
> upstream as jebel-quant/rhiza#1440.

> **`make validate` is gone.** Up to rhiza v1.1.3 there was a `validate` target that
> checked the repo for drift from the template. It was removed by v1.2.1, and naming a
> target the template no longer provides is precisely how this command came to score
> repos as broken. If you meet an older template that still has it, the probe reports
> it as available and it can be run; nothing here assumes it.
>
> Unrelated to `scripts/validate.py`, which `/rhiza:status` runs to check that
> `template.yml` itself is well-formed.

## 2. Report the gate results

Before any scoring, report what the gates said:

- a **PASS / FAIL / unavailable** line per gate;
- failures grouped by file, with the specific rule or error and the line;
- a prioritized list of what to fix first — blocking errors before style nits.

## 3. Gather the design evidence

`Read` **`${CLAUDE_PLUGIN_ROOT}/prompts/design-analysis.md`** and follow it (in a
source checkout, `prompts/design-analysis.md`). Complexity and architecture are the two
subcategories `/quality` must *always* score, and **no `make` gate measures either** —
so that evidence is gathered by hand, or the marks are guesses.

## 4. Score, and offer to file findings

`Read` **`${CLAUDE_PLUGIN_ROOT}/prompts/scorecard.md`** and follow it. It owns the
scoping rule, the subcategory list, the coverage bar, the findings format, and the
issue-filing menu. Feed it the step-2 gate results and the step-3 evidence; it turns
them into marks, then findings, then — only with an explicit selection — issues.

Both files are **internal procedures, not slash commands** — deliberately outside
`commands/` so the user can't invoke them, and `Read` is how you reach them. Don't
restate their rules here or score from memory: the scoping rule in particular is what
stops a managed repo being marked down for its own template.

> **`/quality` is the only command that scores.** `/update` used to invoke it and
> carry a scorecard in its PR; it no longer does — it syncs the template and nothing
> else, so that a template bump PR can't be polluted by `make fmt` rewriting the
> repo's own files. Run `/quality` yourself, whenever you want a score. Nothing
> invokes this command on your behalf, so there is no assessment-only mode to
> switch into.
