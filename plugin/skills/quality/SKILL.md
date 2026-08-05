---
description: Run the Rhiza code-quality gates and score this repo, then optionally file findings as issues. Falls back to a design-led assessment when the repo isn't rhiza-managed or synced. Assesses only — it proposes fixes but never applies them.
argument-hint: "[path or topic to scope the assessment to]  (optional; defaults to the whole repo)"
allowed-tools: Bash(make*), Bash(git*), Bash(gh*), Bash(glab*), Bash(uv*), Bash(uvx*), Bash(python3*), Bash(grep*), Bash(find*), Bash(wc*), Bash(sed*), Bash(sort*), Bash(uniq*), Grep, Glob, Read, Edit, Write, AskUserQuestion
---

Assess the quality of the **current working directory's repo** against Rhiza
standards. This is the global variant of the per-repo `rhiza_quality` command
synced from `jebel-quant/rhiza`; it adapts to whichever repo it runs in by
reading that repo's `CLAUDE.md`, `.rhiza/template.lock`, and git remote at
runtime.

## 0. Establish the mode — how much of this repo is Rhiza's

These two checks come **first — before any `make`, any tool, any analysis**, because
they decide which half of this command applies:

```bash
test -f .rhiza/template.yml   # rhiza-managed at all?
test -f .rhiza/rhiza.mk       # ...and actually synced?
```

| Both present | **Full mode** — the template's gates plus the design assessment. |
| `template.yml` only | **Degraded mode** — managed but never synced, the state `/init` deliberately leaves behind. Mention `/rhiza:update` performs the first sync, then continue. |
| Neither | **Degraded mode** — not rhiza-managed. Mention `/rhiza:init` once, as information, then continue. |

**Degraded mode is a narrower assessment, not a refusal.** Skip the template-delivered
gates, run whatever the repo's *own* makefile provides, and score the design work in
full. Say which mode you're in before the first gate, so nothing that follows is read
as a Rhiza verdict when it isn't.

**What degrading must never become is running the template's gates anyway.** Every
numbered gate below is a `make` target the sync delivers; without `.rhiza/rhiza.mk`
they fail with "No rule to make target", and reporting those as FAIL describes a broken
repo when the truth is an unsynced one. That was the original reason this was a hard
stop, and it still holds — the answer is to *not run them and mark them unavailable*,
which is exactly what the existing out-of-scope rule already does for a reduced profile.
An unavailable gate is never a FAIL, in any mode.

So in degraded mode:

- **Skip** every gate in the numbered list, and every `.rhiza/`-dependent step:
  `make rhiza-test` (there is no `.rhiza/tests/`), template fidelity, and the
  `known-issues.md` lookup (it is keyed by the template ref in `.rhiza/template.lock`,
  which does not exist).
- **Run** the targets `check_make_targets.py` reports as `undeclared` — the repo's own
  documented ones. An unmanaged repo with a working `make test` and `make lint` is the
  Go/Rust case generalised: the named list describes a template this repo isn't using,
  and the discovered targets are the real gates. Score those.
- **Do steps 3 and 4 in full.** The design analysis reads source, not `.rhiza/`, so it
  is unaffected — and in degraded mode it carries most of the assessment.
- **Score nothing you did not measure.** A skipped gate is out-of-scope, never a 0 and
  never an assumed pass.

### Which language is this repo?

**Ask before assuming.** The gate list below, `src/`, `pyproject.toml` and the
test-layout rule are all the **Python** profile. `/rhiza:init` supports Python, Go and
Rust, so a synced repo may legitimately be none of those things (**keep the quotes**;
in a source checkout use the repo-relative path):

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/language_profile.py" --json
```

It returns the language and how it was determined, plus the **source root**, the
**manifest**, and whether `test_layout_applies`. Feed those to `design-analysis.md` and
`scorecard.md` instead of the Python defaults. Exit **1** means the language could not
be determined — say so and score conservatively rather than assuming Python.

**Profiles vary, so probe before running:**
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/check_make_targets.py"
```
It reads the gate list **out of this file's numbered list below** — so the probe can
never drift from what you're about to run — and reports each target as `available` or
`unavailable`, using `make -n` so no recipe executes.

It also reports **`undeclared`**: targets the repo documents (`target: ## description`)
that the list below never named. On a Python repo those are mostly noise (`book`,
`clean`). On a Go or Rust repo they are the point — the named gates will nearly all be
unavailable, because the list describes a template that repo isn't using, and the
discovered targets are the real ones. **Run the relevant discovered targets and score
them**; reporting "no gates available" on a repo with a working `make test` is the
unsynced-repo error wearing a different hat.

Discovery rather than a per-language table is deliberate: this plugin has not seen the
Go and Rust templates' makefiles, and a table of targets it guessed at would be prose
asserting things about repos it has never run in.

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
   `uv run --python 3.12 --no-project python plugin/scripts/check_test_layout.py` in a source checkout). It fails when a
   source module has no mirrored `test_<name>.py`, a source `class A` has no
   `TestA`, or a test file/`Test*` class has no source counterpart. Test files
   listed in `.rhiza/template.lock` are skipped — a synced repo is not marked
   down for a file its template wrote and it cannot move (the same principle as
   the scorecard's "never mark a repo down for its own template"), which is what
   `tests/test_rhiza_packaging.py` hit from rhiza v1.3.2 on. A repo that
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

- Run each gate as a single, bare `make <target>` command — one Bash call per gate, no
  pipe, redirect, chain or `cd` prefix. Read the output directly from the tool result
  rather than capturing it to a file. **The plugin's `PreToolUse` hook enforces this**
  (`plugin/hooks/hooks.json` → `plugin/scripts/hook_bash_guard.py`): a compound `make` is denied with
  the reason, so re-run it bare. The hook is a backstop, not a substitute — it may be
  absent in an older Claude Code, and the rule holds either way.
- Run all available gates even after an early failure, so the full picture is
  visible rather than stopping at the first red.
- **If a gate fails, `Read`
  `${CLAUDE_PLUGIN_ROOT}/prompts/known-issues.md` before diagnosing** (in a source
  checkout, `plugin/prompts/known-issues.md`). Some failures are upstream and unsatisfiable
  here, and it says which, keyed by the template ref in `.rhiza/template.lock`. A listed
  one is scored **out-of-scope**, not FAIL — and one of them must specifically *not* be
  "fixed", because the obvious fix makes the package unbuildable. A failure that isn't
  listed is in scope; carry on.
- Then show the relevant output and diagnose the root cause.
  **Propose the fix; don't apply it** — this command assesses, and a scoring run
  that quietly edits code makes its own score unreproducible. The exception is
  whatever `make fmt` auto-formats as part of running, which is unavoidable.
- If `$ARGUMENTS` is non-empty, scope the assessment to that path or topic
  instead of the whole repo.
- End with a concise PASS/FAIL summary per gate.

**`make rhiza-test`.** Runs the test-suite the template syncs into `.rhiza/tests/` —
the `[project]` structure gate, docstring coverage, README validation. A failure there
is usually a *local* gap the template is checking for, so it is in scope; a failure in
the synced test files themselves is upstream — and `plugin/prompts/known-issues.md` names the
one that is unsatisfiable rather than merely upstream.

## 2. Report the gate results

Before any scoring, report what the gates said:

- a **PASS / FAIL / unavailable** line per gate;
- failures grouped by file, with the specific rule or error and the line;
- a prioritized list of what to fix first — blocking errors before style nits.

**Whenever the base is narrower than a full Python run, say so.** Two situations
produce that, and they compound:

- **A Rust or Go repo.** The numbered gate list above is the **Python** profile — the
  one this plugin has actually run against. On another language most of those targets
  are unavailable, the marks come from the targets `check_make_targets.py`
  *discovered*, and language-specific subcategories (test-layout parity above all) are
  out-of-scope rather than measured.
- **Degraded mode** (step 0). No template gate ran at all; every mark rests on the
  repo's own discovered targets plus the design analysis.

So state, in the report:

- **which mode** produced it, and — in degraded mode — that no Rhiza gate ran;
- that the gates were **discovered**, and which ones ran;
- which subcategories were skipped as not applicable, and why (no template / not this
  language);
- that the result rests on a narrower base and **is not comparable** to a full run.

A scorecard that silently rests on fewer gates reads as an equivalent number. Saying so
costs three lines and is the difference between a narrower score and a misleading one.
This matters most in degraded mode, where the number is *least* comparable and the
temptation to read it as "the Rhiza score" is strongest.

## 3. Gather the design evidence

`Read` **`${CLAUDE_PLUGIN_ROOT}/prompts/design-analysis.md`** and follow it (in a
source checkout, `plugin/prompts/design-analysis.md`). Complexity and architecture are the two
subcategories `/quality` must *always* score, and **no `make` gate measures either** —
so that evidence is gathered by hand, or the marks are guesses.

## 4. Score, and offer to file findings

`Read` **`${CLAUDE_PLUGIN_ROOT}/prompts/scorecard.md`** and follow it. It owns the
scoping rule, the subcategory list, the coverage bar, the findings format, and the
issue-filing menu. Feed it the step-2 gate results and the step-3 evidence; it turns
them into marks, then findings, then — only with an explicit selection — issues.

Both files are **internal procedures, not slash commands** — deliberately kept out of
any directory Claude Code scans, so the user can't invoke them, and `Read` is how you
reach them. Don't
restate their rules here or score from memory: the scoping rule in particular is what
stops a managed repo being marked down for its own template.

> **`/quality` is the only command that scores.** `/update` used to invoke it and
> carry a scorecard in its PR; it no longer does — it syncs the template and nothing
> else, so that a template bump PR can't be polluted by `make fmt` rewriting the
> repo's own files. Run `/quality` yourself, whenever you want a score. Nothing
> invokes this command on your behalf, so there is no assessment-only mode to
> switch into.
