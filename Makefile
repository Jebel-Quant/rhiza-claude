.DEFAULT_GOAL := help

.PHONY: help install lint audit complexity test e2e portable book book-serve paper paper-figures clean changelog

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
# git (bandit) and the eight workflows holding write permissions (zizmor).
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
