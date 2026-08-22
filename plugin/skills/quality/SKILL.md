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
test -f .rhiza/template.yml    # rhiza-managed at all?
test -f .rhiza/template.lock   # ...and actually synced?
```

| Both present | **Full mode** — the template's gates plus the design assessment. |
| `template.yml` only | **Degraded mode** — managed but never synced, the state `/init` deliberately leaves behind. Mention `/rhiza:update` performs the first sync, then continue. |
| Neither | **Degraded mode** — not rhiza-managed. Mention `/rhiza:init` once, as information, then continue. |

**The second probe is the lock, not a synced file.** It used to be `.rhiza/rhiza.mk`,
which was a proxy: the sync delivered it, so its presence stood in for "a sync has
happened". Template v1.4 retired the make layer and stopped shipping it, and the proxy
inverted — every correctly and fully synced v1.4 repo answered "never synced" and was
quietly assessed in degraded mode, which is the *narrower* assessment and understates the
repo. `.rhiza/template.lock` is not a proxy: every sync writes it, at every template
version, and its `files:` block is the authoritative record of what was materialised.
`/rhiza:init` deliberately leaves it absent, which is exactly the never-synced state the
table's middle row describes. **Probe for an artefact the sync itself writes, never for
one a particular template version happened to ship.**

**Degraded mode is a narrower assessment, not a refusal.** Skip the template-delivered
gates, run whatever the repo's *own* makefile provides, and score the design work in
full. Say which mode you're in before the first gate, so nothing that follows is read
as a Rhiza verdict when it isn't.

**What degrading must never become is running the template's gates anyway.** Every
numbered gate below is a gate the sync provides — a `make` target through v1.3, a
`rhiza-task` task from v1.4 — and in an unsynced repo it exists in neither form, so
running it fails with "No rule to make target" and reporting that as FAIL describes a
broken repo when the truth is an unsynced one. That was the original reason this was a hard
stop, and it still holds — the answer is to *not run them and mark them unavailable*,
which is exactly what the existing out-of-scope rule already does for a reduced profile.
An unavailable gate is never a FAIL, in any mode.

So in degraded mode:

- **Skip** the template-delivered gates, and every `.rhiza/`-dependent step:
  `make rhiza-test` (there is no `.rhiza/tests/`), template fidelity, and the
  `known-issues.md` lookup (it is keyed by the template ref in `.rhiza/template.lock`,
  which does not exist).
- **Except `fmt`, `typecheck`, `docs-coverage` and `deptry`, which resolve in any repo.**
  Each falls back to the repo's **own** tool config — see step 1 for the ladder and its
  one hard limit: no config means out-of-scope, never the template's flags. These four are
  gated in most mature repos, so skipping them reported gaps that usually are not there.
- **Run the bundled checkers, which need no template at all** — test-layout parity
  (gate 8, where `test_layout_applies`) and the example checker (gate 9). Both are
  stdlib-only Python this plugin ships, so neither depends on a sync. Gate 9's README half
  is language-neutral and runs on a Rust or Go repo too; only its docstring half is
  Python's. It matters most here: the docstring and README checks a managed repo gets from
  `make rhiza-test` have **no counterpart** in an unmanaged one, so without it nothing at
  all asks whether this repo's documented examples still work.
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
never drift from what you're about to run — and reports each target as `available`,
`unavailable` or `undetermined`, using `make -n` so no recipe executes.

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

**`undetermined` means the probe could not tell, and that is not availability.** A repo
whose `Makefile` is a shim — template v1.4 retired the make layer for a task runner,
leaving a `%:` rule that forwards anything it cannot resolve — answers `make -n` with
success for *every* target, typos included. So all the named gates come back
undetermined, and running them off the back of the probe is how a gate that does not
exist gets run and its "unknown task" error scored as a FAIL. In that repo:

- **Enumerate the real tasks first**, with a bare `make help`. On a shim that is the
  runner listing itself, which is the only place the task names exist — there is no
  synced make layer left to read and nothing on disk to parse.
- **Match each named gate to a task before running it.** The names moved: the `deptry`
  gate is the `deps` task. Score the task you actually ran, under the concern the gate
  names.
- **A gate with no matching task was never provided** — out-of-scope, never FAIL, the
  same as `unavailable`.

**Exit 1 means no makefile at all, and that is two different repos.** Read the note the
probe prints, because they need opposite advice:

- **No `.rhiza/template.lock` either** — unsynced, which step 0 already put in degraded
  mode. Say so and move on.
- **The lock is present** — a **fully synced v1.4 repo that kept no shim `Makefile`.**
  The `Makefile` is repo-owned from v1.4 on, so having none is a legitimate state and not
  a broken sync. This repo is in **full mode**; its gates moved rather than went missing,
  so they are reported `undetermined`, and telling it to run `/rhiza:update` is telling it
  to redo what it has already done. Enumerate the real tasks and run each gate through the
  runner instead:

  ```bash
  uvx rhiza-task list
  ```

  Then run each gate as a bare `uvx rhiza-task <task>`, matching it to a task first —
  the names carried over from the make layer, with `deps` for the `deptry` gate. A gate
  with no matching task was never provided: out-of-scope, never FAIL. This is the same
  discipline as the shim case above, minus the makefile — and the same rule holds about
  what you must not do instead, which is supply your own thresholds.

`typecheck`, `security` and `docs-coverage` come from the template's *tests* bundle and
`deptry`/`fmt` from *core*, so a reduced profile legitimately lacks some. **Run only the
available gates.** An unavailable one is scored **out-of-scope**, exactly like the
Rhiza-owned rule below — never FAIL.

## 1. Run the gates

Follow the command-execution policy: always prefer the repo's own front door —
`make <target>`, or `uvx rhiza-task <task>` in a v1.4 repo that kept no makefile — and
never invoke `.venv/bin/...` directly. Run them in order — cheapest checks first so fast
failures surface before the slow test suite — and collect results:

1. `make fmt` — pre-commit hooks + linting (ruff format/check, markdownlint, bandit, actionlint, …). **This one resolves in any repo — see below.**
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
9. **Docstring examples and README fences** — run the bundled checker
   (**keep the quotes**; in a source checkout use `plugin/scripts/check_doc_examples.py`):

   ```bash
   uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/check_doc_examples.py" --source-root <SOURCE_ROOT> --json
   ```

   `<SOURCE_ROOT>` is the one `language_profile.py` reported — never an assumed `src/`.
   It answers two questions no other gate asks: where the **doctest examples** in the
   docstrings are, and whether every **README fence** parses as the language it claims
   (`bash -n` for shell, `compile()` for Python). Add **`--run`** to *execute* them —
   `doctest` per module, and the `python` fences diffed against the ```result``` block
   that follows them — which is the half that catches an example gone stale. Exit **1**
   means an example is broken; exit **2** means there was nothing to check (no source
   root, no README), which is out-of-scope in the usual way, never FAIL. Read the next
   section before passing `--run`.

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

**The rule is about the thresholds, not about `make`.** Where v1.4 moved them into a
pinned `rhiza-task` release and the repo's `[tool.rhiza-task]` table, `uvx rhiza-task
<task>` is that same entry point and carries that same configuration; `uvx ruff check`
still is not.

### Why the examples are a gate of their own

`make docs-coverage` asks *"is there a docstring?"* and `markdownlint` asks *"is this
well-formed markdown?"*. Neither asks whether what the documentation **claims** is still
true, and that is the failure with the longest half-life in a repo: a docstring whose
`>>>` example returns something else now, or a README quickstart whose first command no
longer parses. Both keep rendering perfectly. The person who finds out is a newcomer, at
the worst possible moment, and a 10 on docstring coverage is exactly what makes it
invisible.

Three habits keep this gate honest:

- **`--run` is opt-in, and its cost is real.** Without it the examples are *parsed*:
  malformed doctests and unparseable fences are caught with no import and no
  dependencies. With it they are *executed* — which imports the repo's modules and runs
  its README's Python, i.e. whatever module-level code they carry. That is the same trust
  boundary `make test` crosses, so pass it once you have already decided to run the suite;
  it is not a step to take on a repo you were asked only to read. Shell fences are
  **never** executed either way — a README's shell is routinely `make clean`, `git push`,
  `rm -rf`, and a fence that cannot parse is a documentation bug without running it.
- **Execute in the repo's own environment, or don't score that half.** Under
  `--no-project` the interpreter has none of the project's dependencies, so most modules
  fail to import. The checker reports those as **unimportable — unmeasured, not failing**,
  and so must you: a missing dependency is a fact about how you invoked it, not a defect
  in the docstring. When the repo has an environment (`uv run` inside a `uv` project,
  `make test`'s own runner), run the `--run` pass there and say which one you used.
- **"0 examples" is a finding, not a pass.** A repo whose docstrings carry no examples
  scores full marks on every gate above while documenting nothing executable. Report it
  under user-facing documentation as the gap it is — and say plainly that the gate ran and
  found nothing to check, rather than letting silence read as green.

**In full mode this is a second look, not a second score.** `make rhiza-test` already
runs the template's own `test_docstrings.py`, `test_readme.py` and
`test_readme_validation.py` — the three checks this checker reimplements, on the same
`+RHIZA_SKIP` convention. So in full mode take the verdict from `make rhiza-test`, run the
checker **without `--run`** for the inventory it adds (where the examples are, how many,
which fences carry no language at all), and don't count one result twice. In degraded mode
there is no `.rhiza/tests/`, nothing else checks any of this, and the checker *is* the
gate.

### Four gates resolve in any repo

**Read the rule above precisely: what is forbidden is running a tool with *thresholds
you supplied*.** It is not "only ever `make <target>`". Formatting, type checking,
docstring coverage and dependency hygiene are gated in most mature repos, so reporting
them all as unavailable usually understates coverage rather than describing a gap.

Each resolves the same way — **stop at the first hit** — and they keep the template's
order, so a fast failure still surfaces before the slow ones:

| Gate | Rung 1 | Rung 2: the repo's **own** config | Needs |
| --- | --- | --- | --- |
| `fmt` | `make fmt` | `.pre-commit-config.yaml` via `uvx prek run --all-files` (or `pre-commit`, if that is what CI names) | — |
| `typecheck` | `make typecheck` | `[tool.mypy]` in `pyproject.toml`, or `mypy.ini` / `setup.cfg` → `uvx mypy <source_root>` | a source root |
| `docs-coverage` | `make docs-coverage` | `[tool.interrogate]` in `pyproject.toml` → `uvx interrogate <source_root>` | a source root |
| `deptry` | `make deptry` | `[tool.deptry]`, or a dependency manifest to read → `uvx deptry <source_root>` | a source root **and a manifest** |

**Rung 2 is not the forbidden case**: every argument, threshold and exclusion still comes
from the repo's committed config, which is the whole thing the rule protects. The runner
is an entry point, not a judgement. Pass **no flags** — never `--strict`, never
`--fail-under`, never anything the repo did not ask for.

**And pass no path either, when the config already declares one.** A config may name its
own scope — `files = plugin/scripts` in `mypy.ini`, `files`/`packages` under
`[tool.mypy]`, `paths` under `[tool.interrogate]`. Appending the source root there does
not narrow the run, it **overrides** the repo's own scoping and measures a different
tree. This repo is the case: `mypy.ini` says `files = plugin/scripts`, so bare `uvx mypy`
checks the 45 modules CI checks, while `uvx mypy .` would sweep in `tests/` and report on
code the repo deliberately does not type-check. So: **read the config first.** Scope
declared → run the tool bare. No scope declared → pass `<source_root>` and say which one
you used.

**No config means rung 3: out-of-scope.** Do **not** fall back to the template's flags.
Copying `mypy --strict` or interrogate's threshold onto a repo that never chose them is
exactly how `interrogate` comes to report FAILED at 99.5% where a configured hook passes
— it measures a standard the repo never adopted, and then files issues for it. A repo
with no type-checking config has not failed type checking; it has declined to gate it,
which is a finding about *process*, reportable under step 3, not a FAIL here.

**`<source_root>` comes from `language_profile.py`, never from assuming `src/`.** On a
manifest-less repo the census reports `.`, which sweeps in `tests/` and anything else at
the root — so say which root was used, because `mypy .` and `mypy src` are different
measurements and only one of them is what CI would run.

**`deptry` additionally needs a manifest, not just a source root.** It works by comparing
*declared* dependencies against *imported* ones, so with nothing declaring them it has no
left-hand side. `language_profile.py` reports `manifest_present` for exactly this kind of
question: false means rung 3, and the honest finding is "dependencies are not declared
anywhere", which is worth more than a tool error.

**`security` and `rhiza-test` stay template-only.** `rhiza-test` runs the template's own
bundled suite, which by definition is not there. `security` is pip-audit plus bandit, and
bandit is commonly a pre-commit hook already — so in most repos it is *already covered* by
`fmt` at rung 2, and running it again as its own gate would double-count one result.
Check whether the hook run included it before reporting a security gap.

**A discovered target is deliberately not a rung.** It is tempting to let a `lint`,
`format` or `check` target stand in, but the name does not tell you the scope: this
repo's `make lint` runs mypy, interrogate, test-layout parity and the contract checkers
alongside ruff, so scoring it as `fmt` would credit formatting with most of the
toolchain. Matching on a target name is inference about what a target does, and that is
the same class of mistake as supplying your own thresholds — just wearing a `make`
prefix. Go to the config, which says exactly what runs.

**Say which rung answered**, as the narrower-base rule requires: "fmt via prek over
`.pre-commit-config.yaml`" is not the same evidence as `make fmt`.

**And score the underlying run once.** If a discovered target already ran those hooks,
`fmt` and that target rest on the same evidence — say so rather than reporting two
independent passes.

**None of this licenses rung 2 with a config you wrote**, or bare `uvx ruff check` when
a config exists. If there is no target and no config, the answer is rung 3.

Guidelines:

- Run each gate as a single, bare `make <target>` command — or a bare
  `uvx rhiza-task <task>` where that is the front door — one Bash call per gate, no
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

- a **PASS / FAIL / unavailable** line per gate — an undetermined gate you resolved to a
  task is reported under the task you ran, and one you could not resolve is `unavailable`;
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

## 3. Degraded mode only — assess the infrastructure the template would have owned

**Skip this section entirely in full mode.** In a managed repo every file below is
Rhiza-owned, and scoring it would be the exact mistake the scoping rule exists to
prevent. In degraded mode there is no template, so all of it is the repo's own work —
and *nothing else is checking it*. This is where degraded mode stops being a reduced
assessment and starts being a different one.

The gates in step 1 answer "is the code clean?". These answer **"does this repo's
quality survive contact with a second contributor?"** — which is what a template buys
you, and what its absence puts at risk.

- **Are the gates wired into CI, or only runnable locally?** Read `.github/workflows/`
  (or `.gitlab-ci.yml`) and check that the targets you just ran are actually invoked
  there. A `make test` that only ever runs on the author's machine is a gate in name
  only: it constrains one person's habits, not the repo. **This is the single
  highest-value check in degraded mode** — a managed repo gets CI wiring from the
  template and cannot get this wrong, so an unmanaged one is where it silently goes
  missing.
- **Is the toolchain reproducible?** A lockfile committed, a pinned language version,
  and third-party CI actions pinned to a tag or SHA rather than a moving branch. Name
  what is missing; an unpinned `@main` in someone else's action is a supply-chain
  decision the repo made without recording it.
- **Is there a documented way in?** `make help`, or a README section that names the
  commands. If the only way to learn how to run the gates is to read the `Makefile`,
  say so.
- **Does a present config actually run?** A `.pre-commit-config.yaml` that no CI job
  invokes is a file, not a gate — the same trap as the CI point above, one level down.

**Gather, don't assume.** Every claim names the file you read and the line that
supports it, exactly as `design-analysis.md` requires. "No CI" and "CI that doesn't run
the gates" are different findings with different fixes, and only reading the workflow
tells them apart.

**Score these as their own subcategories** — CI wiring, toolchain reproducibility,
contributor onboarding — and say plainly that they are in scope *because* the repo is
unmanaged. A reader comparing this run to a managed repo's needs to know these marks
have no counterpart there, rather than assuming the managed repo scored 10 on them.

**And if the answer is "adopt the template", say it once.** `/rhiza:init` exists and
wiring CI by hand is work; noting that is useful. Repeating it per finding turns an
assessment into a sales pitch, and step 0 already said it once.

## 4. Gather the design evidence

`Read` **`${CLAUDE_PLUGIN_ROOT}/prompts/design-analysis.md`** and follow it (in a
source checkout, `plugin/prompts/design-analysis.md`). Complexity and architecture are the two
subcategories `/quality` must *always* score, and **no `make` gate measures either** —
so that evidence is gathered by hand, or the marks are guesses.

## 5. Score, and offer to file findings

`Read` **`${CLAUDE_PLUGIN_ROOT}/prompts/scorecard.md`** and follow it. It owns the
scoping rule, the subcategory list, the coverage bar, the findings format, and the
issue-filing menu. Feed it the step-2 gate results, the step-3 infrastructure findings
(degraded mode only) and the step-4 design evidence; it turns
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
