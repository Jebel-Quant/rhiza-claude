# Scorecard (internal procedure)

> **Not a slash command.** This file lives in `prompts/`, which Claude Code does not
> scan for commands, so the user cannot invoke it. `/rhiza:quality` reads it and follows it once the gates have
> run and `plugin/prompts/design-analysis.md` has produced its evidence.

Turn gate results and design evidence into 1–10 marks, then into a findings list, then
optionally into issues. **Nothing here re-runs a gate or gathers new evidence** — if a
number is missing, that subcategory is unscored, not guessed.

## 1. The scoping rule — read this before assigning any mark

**Score only what this repo owns.** A rhiza-managed repo syncs its dev infrastructure
from `jebel-quant/rhiza`; `CLAUDE.md` holds the authoritative split and the `files:`
block of `.rhiza/template.lock` is the machine-generated list of synced paths.

- **In scope:** the repo's source root, its tests, its **manifest**, `README.md`,
  project-specific docs, `.rhiza/template.yml`, and any locally-hardened config. The
  source root and manifest are language-dependent — `src/` + `pyproject.toml` for
  Python, `.` + `go.mod` for Go, `src/` + `Cargo.toml` for Rust — and
  `plugin/scripts/language_profile.py` reports which apply, so don't assume the Python pair.
- **Out of scope:** `.github/workflows/*`, `Makefile`, `.pre-commit-config.yaml`,
  `pytest.ini`, `ruff.toml`, the typecheck/mutation/fuzzing targets — everything the
  template delivers.

A gap in a Rhiza-owned file is fixed **upstream**, not here. Note it as
"upstream/out-of-scope" rather than scoring it against this repo. Without this rule
every managed repo would be marked down for its own template, which would make the
score meaningless and identical everywhere.

Likewise, a gate that was **unavailable** (not in this profile — see `/quality`'s
step 0) is out-of-scope, never a FAIL.

**In degraded mode the split doesn't exist, and that inverts the rule.** When
`/quality` runs on a repo that is unmanaged or unsynced, there is no template, so
nothing is Rhiza-owned: the `Makefile`, the workflows, `.pre-commit-config.yaml` and
the rest are the repo's **own** work and are all **in scope**. Carrying the exclusion
list over unchanged would silently drop that repo's real infrastructure out of its own
assessment — the mirror image of the mistake this rule exists to prevent. Score what
the repo owns, which in degraded mode is everything.

Two consequences follow, and neither is a judgement call:

- **Template fidelity is not scored** — there is no template to be faithful to. Mark
  it not-applicable, never 0.
- **`/quality`'s own skipped gates are not findings.** "Not rhiza-managed" is a fact
  about the repo, not a defect in it. Do not file it, and do not let it depress a mark.
  If adopting the template would genuinely help, that belongs in the closing remark as
  a suggestion, at most once.

**Template mode inverts the rule the same way, for the opposite reason** — see
`/quality`'s step 0. The repo it applies to is the template itself, identified by
`.rhiza/template-bundles.yml` with no `template.yml` above it. Everything the exclusion
list names is *in scope* there too, but not because there is no template: because those
files **are** the template, and shipping them is what this repo does. Three differences
from degraded mode, all of them corrections:

- **They are the product, so they carry more weight, not less.** In degraded mode the
  infrastructure marks describe a repo doing by hand what a template would have given
  it. Here they describe what every consumer will inherit — the highest-value marks on
  the page rather than a consolation for the ones that could not be measured.
- **"Upstream/out-of-scope" is not available.** That escape hatch exists because a gap
  in a Rhiza-owned file is fixed in the template repo. In the template repo, it is fixed
  *here* — so a real gap is a finding, and deferring it upstream defers it to itself.
- **Never suggest adopting the template.** The one-line suggestion above is wrong here,
  not merely redundant; omit it. Template fidelity is still not-applicable, for the
  same reason as degraded mode.

**And a check that doesn't apply to the language is out-of-scope too.** Test-layout
parity is the clearest case: `check_test_layout.py` is built on Python module and class
naming, so it says nothing about a Go or Rust repo. `language_profile.py` reports
`test_layout_applies` for exactly this reason. Scoring a Rust crate down for failing a
Python convention is the same mistake as scoring a managed repo down for its template.

## 2. Subcategories

**Always score both design subcategories**, from `plugin/prompts/design-analysis.md`'s
evidence. Add the others that fit what you actually observed.

- **Gate-derived:** linting/style, type safety, docstring/API-doc coverage, test pass
  rate, test coverage & depth, dependency & security hygiene, template fidelity
  (`make validate` drift), **executable documentation** (`/quality`'s gate 9).
- **Design (always both):** *code complexity* — average CC, the worst C-or-worse
  blocks, maintainability index, size of the largest functions/modules; *overall
  architecture* — layering & dependency direction, coupling/cohesion, module
  responsibility, composition pattern, and the absence of import cycles.
- **Additional (score those with signal):**
  - *test design quality* — do tests assert behaviour or mirror the implementation?
    Mock depth and brittleness: a brittle suite can hit 100% coverage and still pin
    internals, so coverage alone doesn't earn this mark.
  - *error handling & CLI UX* — exit codes, actionable messages, failure modes.
  - *security posture & trust boundaries* — input validation of `template.yml` and
    config, path traversal in any path remapping, `subprocess` usage.
  - *public API / semver discipline* — stability of the CLI surface and exported models.
  - *cross-platform robustness* — Windows path and symlink behaviour.
  - *idempotency & failure recovery* — repeat-run safety, partial-failure cleanup.
  - *user-facing documentation* — README and usage, not just docstrings.

**Executable documentation is scored apart from docstring coverage, and the two must not
be merged.** `interrogate` measures whether a docstring *exists*; gate 9 measures whether
what it *claims* is still true — a distinction a repo can fail in only one direction, and
usually does. Three results, three different marks:

- **A failing example** — a doctest that no longer evaluates to its documented output, or
  a README fence that doesn't parse — is a defect in shipped documentation. Score it as
  one, with the file and line, and file the finding.
- **No examples at all** is a gap in this subcategory, not a 10 by default. A repo can
  hold 100% docstring coverage while documenting nothing anyone can run; say so, and keep
  the mark honest rather than letting the silence pass as green.
- **Unmeasured is neither.** Modules the checker could not import, and the whole gate when
  it exits 2, are out-of-scope by the rule above — never a FAIL, and never an assumed
  pass. Say which half was measured and in what environment, since a `--run` pass without
  the project's dependencies measures very little.

**Coverage.** `make test` enforces `COVERAGE_FAIL_UNDER` (default 90%; many projects
raise it to 100%). **The configured threshold is the bar for a 10** — not a number you
pick. Treat anything below it on locally-owned `src/` as a gap, and report uncovered
lines as `file:line` with the test that would close each.

## 3. Present the marks

For each subcategory: **the score, a one-line justification grounded in the evidence**
(gate output, radon metrics, the import graph, or a named code read), and what would
raise it. A justification that doesn't cite evidence means the mark isn't earned —
drop the subcategory instead.

Close with an overall score and **the single highest-leverage improvement**.

If everything passes, say so plainly — but still produce the marks. A clean gate run is
not automatically a 10 everywhere.

## 4. Findings

One per subcategory scoring below 10; skip any that are maxed. Each carries:

- a **self-contained title** (e.g. `Raise coverage on src/foo.py from 84% to 100%`);
- the **subcategory** and **current→target** score;
- the specific **file(s)/lines or config** to change;
- a crisp **`done when…`** acceptance criterion;
- a one-line **evidence** snippet from the gate output or analysis.

Order by leverage — biggest score gain for least effort first. Keep them in scope:
flag anything Rhiza-owned as upstream rather than listing it as a local action.

**This is a list of recommendations.** Do not change code.

## 5. Offer to file them — by menu, never free text

Present the findings as an `AskUserQuestion` multi-select (`multiSelect: true`), one
option per finding labelled by its title, so the user picks exactly which to file —
**including none**. Create nothing without an explicit selection.

For each selected finding, write its body to a file and create one issue with the
bundled mapper, which detects the platform and picks the CLI:
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/platform_cli.py" \
  issue-create --title <TITLE> --body-file <BODY>
```
Don't hand-write `gh issue create` / `glab issue create`: they differ by more than the
binary name, and `glab issue create` has **no** body-file flag at all — the mapper reads
the file and passes the text inline. Exit **1** means the CLI is missing or
unauthenticated; say so and skip, and don't substitute another mechanism.

Each issue must be self-contained: the title from the finding, and a body carrying the
subcategory, the current→target score, the file(s)/lines or config to change, and the
`done when…` criterion. Report the created issue URLs.
