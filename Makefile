.DEFAULT_GOAL := help

.PHONY: help install lint audit complexity test e2e portable mutate book book-serve paper paper-figures clean changelog

# The interpreter every `uvx` call runs under, read from `.python-version` so the pin
# has exactly one home. Exporting UV_PYTHON is what makes it bind: `.python-version` is
# honoured by `uv run` inside a *project*, and this repo deliberately has no
# `pyproject.toml`, so `uvx` would otherwise pick whatever interpreter is newest — which
# is how `make test` came to run on 3.14 locally while CI ran 3.12.
export UV_PYTHON := $(shell cat .python-version)

# ...and the versions of the tools it runs. Without this, `uvx` resolves the newest
# release of prek, mypy, pytest and the rest at call time, so a tool release can turn CI
# red with no commit here. `requirements-dev.txt` explains why it is a requirements file
# and not a pyproject.toml.
export UV_CONSTRAINT := $(CURDIR)/requirements-dev.txt

PAPER := rhiza-claude-intro

MARKETPLACE := Jebel-Quant/rhiza-claude
PLUGIN := rhiza@rhiza-claude

# Where `make test` leaves its machine-readable reports. `make book` copies the
# directory into the site (docs/reports/) and renders coverage.xml into the badge
# the README links to, so the published number is always measured, never asserted.
TESTS := _tests

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install the rhiza plugin via the Claude Code CLI
	claude plugin marketplace add $(MARKETPLACE)
	claude plugin install $(PLUGIN)

lint:  ## Run all prek hooks against every file
	uvx prek run --all-files

# Audits this repo's *own* code and CI config, because that is what there is to audit.
# The absence of a dependency scan is deliberate, not an omission: `plugin/scripts/` is
# stdlib-only by gate, so the shipped plugin declares no dependencies and `pip-audit`
# would have an empty left-hand side. The real surface is the Python that shells out to
# rhiza-count: workflows
# git (bandit) and the nine workflows holding write permissions (zizmor).
#
# zizmor fails the build at medium and above, not on everything it prints. The two it
# reports here are advisory and both are deliberate: `npm install -g` in plugin.yml is
# the job installing the very CLI it exists to test, and `ncipollo/release-action` is a
# pinned third-party action zizmor would rather see as a `gh release` script step. Low
# findings still print, so a new one is visible without turning an unrelated PR red.
audit:  ## Security-audit the bundled scripts (bandit) and the workflows (zizmor)
	uvx bandit -q -r plugin/scripts
	uvx zizmor --persona=regular --min-severity=medium .github/workflows/

# The complexity bars this repo states as its own: no block above cyclomatic C(12), every
# maintainability index at A. Scoped to `plugin/scripts/` because that is the scope of the
# bar — `tests/` is exempt, and CLAUDE.md records the six C-grade blocks living there and
# why they stay.
#
# **A report, not a gate.** `radon cc -n C` prints what it finds and exits 0 either way,
# so this target tells you where you stand; it does not turn a PR red. Making it fail
# needs a thresholding wrapper (xenon or equivalent) and is its own decision.
#
# It exists as a *target* rather than as two commands in prose for the reason every other
# `uvx` call here is a target: only inside make does UV_CONSTRAINT bind, so the version is
# the one requirements-dev.txt names. A hand-run `uvx radon` outside make resolves whatever
# release is current, which is how two people read different numbers off the same commit.
# `--total-average` rather than `-a`: with `-n C` filtering the output, `-a` averages only
# the blocks that survived the filter, so `plugin/scripts` printed no average at all (nothing
# matches) and `tests` printed "C (11.67)" — the mean of its six worst blocks, read at a
# glance as the mean of all of them. `--total-average` ignores `-n` and reports the real one.
#
# `tests` is measured here despite the bar stopping at `plugin/scripts`, because CLAUDE.md's
# census table states both rows as this repo's numbers and nothing regenerated them: both
# were committed once and had drifted by roughly 15% before anyone re-measured. Printing
# them is what makes the next drift a diff instead of a discovery.
complexity:  ## Report cyclomatic complexity and maintainability index (the census CLAUDE.md quotes)
	uvx radon cc plugin/scripts -s -n C --total-average
	uvx radon cc tests -s -n C --total-average
	uvx radon mi plugin/scripts -s

# PyYAML is a *test* dependency only — the bundled scripts stay stdlib-only at runtime.
# It is here so the PyYAML arm of `_rhiza_yaml.load_yaml` is exercised and measured:
# with it absent, half of that module's behaviour was invisible to the coverage gate.
#
# One definition of the runner, shared by `test` and `e2e`. The `--with` flags are the
# part that has drifted before: CI once hand-wrote this command line, the Makefile gained
# `--with pyyaml`, and the copy in CI did not — so that arm went unmeasured on a branch
# that was green locally. Anything that runs this suite goes through a target here.
PYTEST := uvx --with pytest-cov --with pyyaml pytest tests/

test:  ## Run the script test suite with a 100% coverage gate
	$(PYTEST) --cov=plugin/scripts --cov-report=term-missing \
		--cov-report=xml:$(TESTS)/coverage.xml \
		--cov-report=html:$(TESTS)/html-coverage \
		--cov-fail-under=100 $(ARGS)

# The end-to-end subset on its own — the tests that clone the real template and drive the
# command chains against a genuinely synced repo. `make test` runs these too; this target
# exists for the one caller that needs them *without* the coverage gate, the weekly
# template-drift job, since a filtered run cannot reach 100% and coverage is not the
# question it asks. Not a substitute for `make test`: it reports no coverage at all, so a
# green `make e2e` says nothing about the gate every other caller has to clear.
e2e:  ## Run only the end-to-end tests, without the coverage gate
	$(PYTEST) -k e2e --no-cov $(ARGS)

# The complement of `e2e`, and the mirror of its argument. This is the subset the
# `cross-platform` CI job runs on macOS and Windows.
#
# **Why not `make test` there.** Two reasons, and neither is about speed alone. The e2e
# fixtures clone the real template and drive `cargo`, `go` and `glab` against it — the
# slowest half of the suite and the half least likely to say anything about *path
# handling*, which is the whole reason a non-Linux runner is worth paying for. And the
# coverage gate cannot be met by a filtered run, so `make test` would fail there for a
# reason that has nothing to do with the platform.
#
# Not a substitute for `make test`: it reports no coverage and skips the e2e tests, so a
# green `make portable` says nothing about the gate every PR still clears on Linux. That
# is the same caveat `e2e` carries, for the same reason — both are narrowings that exist
# for exactly one caller.
portable:  ## Run the unit tests without e2e or the coverage gate (the cross-platform CI subset)
	$(PYTEST) -k "not e2e" --no-cov $(ARGS)

# --------------------------------------------------------------------------- #
# Mutation testing — deliberately NOT part of `make test`
# --------------------------------------------------------------------------- #
#
# 100% branch coverage says every arm *ran*; it says nothing about whether any assertion
# would notice if an arm were wrong. That gap is the whole reason this target exists, and
# its first real run found one: `build_lock`'s `strategy = "merge"` can be changed to
# `None` and `tests/scripts/test__rhiza_lock.py` still passes — only `test_sync.py`
# catches it.
#
# Scoped, still — a full-tree run over fifty modules is slow enough to get switched off,
# which is worse than not having it — but scoped to two kinds of module rather than one:
#
#   * the three that decide what lands in a *user's* repository during `/rhiza:update`
#     (`_rhiza_merge`, `_rhiza_lock`, `stage_synced`), where a surviving mutant is the
#     costliest kind: a wrong merge or a wrong staged file set shipping green;
#   * the two prose gates (`check_command_contracts`, `check_prompt_wiring`), where a
#     surviving mutant means **a gate silently not gating** — the same failure as the
#     `_PROTECTED` finding below, one level up. A checker that stops checking reports
#     success, so nothing else in the repo can notice.
#
# The second group was added on the evidence of the first: everything the technique found
# in the sync core was invisible to a 100% line-*and*-branch gate, and there is no reason
# code that guards the build should be exempt from the same question.
#
# **The threshold is "no surviving mutant that changes behaviour", not zero survivors.**
# Five categories are accepted, and each is a deliberate judgement rather than a shrug:
#
#   log text        `log(f"[DEL] {rel}")` → `log(f"XX[DEL] {rel}XX")`. Asserting log
#                   strings, argparse help or a `--json` indent would pin wording that is
#                   meant to be edited freely.
#   `.get` defaults `lock.get("sha", "")` → `lock.get("sha", "XX")`. Reachable only from a
#                   lock missing that field entirely, which the writer cannot produce.
#   equivalent      `sys.path.insert(0, …)` → `insert(1, …)`, or `_BATCH = 100` → `101`.
#                   Same effect for every input that can occur.
#   pragma'd        the `except OSError` arms marked `# pragma: no cover`, e.g. an
#                   unreadable snapshot file. Excluded from coverage for the same reason.
#   module guard    `if __name__ == "__main__":`. Not reachable from an import.
#
# Everything else is a test worth adding. All five modules have now been triaged, and the
# split is recorded because the *ratio* is the useful number — a module that suddenly grows
# real survivors is the signal:
#
#   module                        survivors  real gaps  accepted
#   _rhiza_lock.py                    24          8         16
#   stage_synced.py                   33         14         19
#   _rhiza_merge.py                    9          7          2
#   check_command_contracts.py        70         31         39
#   check_prompt_wiring.py            22          8         14
#
# `_rhiza_merge` is the instructive row: its property tests over generated edit triples
# assert the merged *result*, so only nine mutants survived at all — the fewest of the
# three sync-core modules, from the most intricate code. Its two accepted survivors are
# both pragma'd arms.
#
# What the real gaps were, in every case, was code with 100% line *and* branch coverage
# whose output nothing checked:
#
#   * `_PROTECTED` could be changed to any string — deleting `.rhiza/template.yml`, and
#     with it the repo's rhiza-managed status.
#   * Three `continue`s could become `break`s: skipping an unchanged template file ended
#     the whole scan, and a duplicate lock entry truncated the staged set.
#   * `is_binary(target) or is_binary(upstream) or is_binary(base)` could become `and`,
#     so a text file locally replaced by a binary one would be merged and corrupted.
#   * Every documented exit code, and every key in the summary dicts callers index.
#
# The checkers' 39 came out the same shape, and one class dominated: **a constant listing
# what to check could be corrupted entry by entry.** Four of the six discovery-location
# names rule 6 gates, ten of the twelve exempt shell builtins, and two of the four
# top-of-repo prose files could each be changed to nonsense with the suite green — because
# every test that covered them iterated the constant under test, which cannot detect an
# entry missing from it. Those tests now spell the names out. The rest were five more
# `continue`→`break`s, both `--root` defaults (a broken one makes the hook check an empty
# tree and report success), and the accumulators — `violations = …` for `violations += …`
# in three places, so only the last file's findings survived.
#
# **Two accepted rows in the checkers need their reasoning stated, because "equivalent"
# is doing more work than usual there.** `script_flags` truncates each `add_argument`
# window at the next call; five mutants of that truncation survive, and provably must —
# the flags are unioned across all windows, so text the truncation removes is scanned by
# the *next* window anyway. And the three `replace("\\\n", " ")` joins survive mutation of
# the *replacement* string: what matters is that the newline goes, not what replaces it.
#
# **Bytecode caching makes mutmut over-report survivors, so this target disables it.**
# CPython invalidates a `.pyc` on (source mtime-seconds, source size), and mutmut's
# mutants are almost all exactly four bytes longer than the original (`x` → `XXxXX`), so
# two consecutive same-length mutants written inside one clock second can run against the
# *previous* mutant's cached bytecode. Three mutants here were reported as survivors while
# provably failing the suite on their own — including `_MODEL_INVOCATION_OPT_OUT = None`,
# which cannot even be collected. `PYTHONDONTWRITEBYTECODE=1` in the recipe removes the
# whole class; without it the numbers in the table above are noise at the margin.
# Comma-separated: mutmut takes one `--paths-to-mutate` value and splits it itself.
# Override to narrow a local run to one module, e.g.
#   make mutate MUTATE_MODULES=plugin/scripts/_rhiza_lock.py
MUTATE_MODULES := plugin/scripts/_rhiza_merge.py,plugin/scripts/_rhiza_lock.py,plugin/scripts/stage_synced.py,plugin/scripts/check_command_contracts.py,plugin/scripts/check_prompt_wiring.py

# The tests that actually exercise those modules — not just each one's mirrored file.
# Scoping the runner to the mirror alone over-reports survivors, since much of the sync core
# is driven through `sync.py`: `build_lock`'s `strategy = "merge"` can be mutated to `None`
# and `test__rhiza_lock.py` still passes, while `test_sync.py` catches it. The two checkers
# are the opposite case — nothing else in the suite imports them, so their mirrors are the
# whole story, which is worth knowing before reading a survivor as under-tested.
#
# **Ordered cheapest-first, and that ordering is load-bearing.** mutmut runs the suite with
# `-x`, so a mutant dies at the first failing test and pays for nothing after it. Measured
# on this machine: check_prompt_wiring 0.1s, check_command_contracts 0.4s, resolve_conflicts
# 0.8s, _rhiza_lock 0.9s, stage_synced 1.0s, sync 5.8s, _rhiza_merge 11.3s. Fastest-first
# turns most kills into a one-second run; the previous order billed every mutant for the
# slowest file. `-k 'not e2e'` drops the network-bound tests, which are far too slow to run
# once per mutant.
MUTATE_TESTS := tests/scripts/test_check_prompt_wiring.py \
                tests/scripts/test_check_command_contracts.py \
                tests/scripts/test_resolve_conflicts.py \
                tests/scripts/test__rhiza_lock.py \
                tests/scripts/test_stage_synced.py \
                tests/scripts/test_sync.py \
                tests/scripts/test__rhiza_merge.py

# Pinned to 3.12: mutmut 2.5.1 crashes on 3.14 (`cannot pickle 'itertools.count'`), and
# the whole plugin is run under `--python 3.12` everywhere else anyway.
MUTMUT := uvx --python 3.12 --with pytest --with pyyaml mutmut@2.5.1

# **mutmut rewrites the files it mutates, in place.** An interrupted run therefore leaves a
# live mutant in the working tree — which is exactly how this target's own development
# produced a "failing test" that was really a mutated `_rhiza_lock.py`. So the run happens
# in a throwaway git worktree and the developer's tree is never touched. The trap is worth
# stating out loud because the symptom (a test failing for no reason you can see) is
# thoroughly misleading.
# The worktree is checked out at **HEAD**, so this measures the last commit and not the
# working tree — commit before you read the numbers. That is the right default for the
# scheduled job, and the isolation is worth more than the convenience either way.
MUTATE_WORKTREE := $(TESTS)/mutate

# mutmut exits 2 when mutants survive, which is information rather than breakage: survivors
# are the output of this target, not a malfunction. The exit code is passed through so a
# caller can act on it, and the worktree is removed either way.
mutate:  ## Mutation-test the sync core and the prose gates in an isolated worktree (slow)
	@rm -rf $(MUTATE_WORKTREE)
	@git worktree prune
	@git worktree add --detach -q $(MUTATE_WORKTREE) HEAD
	@mkdir -p $(TESTS)
	@status=0; \
	( cd $(MUTATE_WORKTREE) \
	  && PYTHONDONTWRITEBYTECODE=1 $(MUTMUT) run \
	       --paths-to-mutate "$(MUTATE_MODULES)" \
	       --tests-dir tests/scripts \
	       --runner "python -m pytest -x -q --no-header -p no:cacheprovider -k 'not e2e' $(MUTATE_TESTS)" \
	       --simple-output --no-progress \
	  ; run=$$?; echo; $(MUTMUT) results; \
	    echo "$(MUTATE_MODULES)" | tr ',' '\n' \
	      | while read -r m; do [ -n "$$m" ] && $(MUTMUT) show "$$m"; done \
	      > survivors.diff 2>&1 || true; \
	    exit $$run \
	) || status=$$?; \
	cp $(MUTATE_WORKTREE)/survivors.diff $(TESTS)/mutation-survivors.diff 2>/dev/null || true; \
	git worktree remove --force $(MUTATE_WORKTREE) 2>/dev/null || true; \
	echo "survivor diffs: $(TESTS)/mutation-survivors.diff"; \
	echo "mutmut exit status: $$status (0 = every mutant killed, 2 = some survived)"; \
	exit $$status

# Individual quality checks (mypy, interrogate, test-layout, manifest validation)
# all run via `make lint` (prek). For a single one, use e.g.
# `uvx prek run mypy --all-files`.

# The book depends on the paper: docs/index.md links the PDF, and `--strict` fails on a
# link whose target is missing. Building the paper on every book build is also what keeps
# the .tex honest — a commit that breaks it fails CI rather than shipping a stale PDF.
#
# It depends on `test` for the same reason: the coverage badge and the browsable HTML
# report are *outputs of the run*, so the only way the published badge can be wrong is
# if the suite never ran — and then there is no book either. genbadge goes last because
# `mkdocs build` clears the site directory first.
book: paper test  ## Build the documentation site into _book/ (compiles the paper and runs the tests first)
	mkdir -p docs/reports
	cp -r $(TESTS)/. docs/reports/
	uvx --with mkdocs-material mkdocs build --strict
	uvx "genbadge[coverage]" coverage -i $(TESTS)/coverage.xml -o _book/coverage-badge.svg

book-serve: paper  ## Serve the docs locally with live reload
	uvx --with mkdocs-material mkdocs serve

# Two passes: the first resolves the ToC and page references the second typesets.
# tectonic reruns on its own; pdflatex does not, hence the explicit repeat.
#
# tectonic pulls every LaTeX file the document needs from its bundle CDN as a separate
# request, and that CDN answers 429 often enough to redden a PR that never touched
# paper/. Retrying is worth it *because the fetches are cached*: each attempt resumes
# from the per-user cache rather than starting over, so a run that got halfway gets
# further next time. Four attempts with a growing backoff turn a flaky fetch into a slow
# one. The pdflatex fallback is guarded by `command -v` so a TeX Live machine with no
# tectonic reaches it immediately instead of sleeping through the backoff first.
paper:  ## Build the paper and stage it for the docs site (needs tectonic or pdflatex)
	cd paper && ( \
		if command -v tectonic >/dev/null 2>&1; then \
			for attempt in 1 2 3 4; do \
				tectonic $(PAPER).tex && exit 0; \
				if [ $$attempt -lt 4 ]; then \
					delay=$$((attempt * 20)); \
					echo "tectonic failed (attempt $$attempt/4); retrying in $${delay}s" >&2; \
					sleep $$delay; \
				fi; \
			done; \
		fi; \
		pdflatex -interaction=nonstopmode -halt-on-error $(PAPER).tex \
			&& pdflatex -interaction=nonstopmode -halt-on-error $(PAPER).tex)
	mkdir -p docs/paper
	cp paper/$(PAPER).pdf docs/paper/$(PAPER).pdf

paper-figures:  ## Regenerate the paper's figures from the captured command output
	uv run --with pillow python paper/render_figures.py

clean:  ## Remove generated caches and artifacts (ruff cache, __pycache__, _book, test reports, paper build)
	rm -rf .ruff_cache _book $(TESTS) docs/reports docs/paper
	rm -f paper/*.aux paper/*.log paper/*.out paper/*.pdf
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

changelog:  ## Regenerate CHANGELOG.md from conventional commits
	uvx git-cliff --output CHANGELOG.md
