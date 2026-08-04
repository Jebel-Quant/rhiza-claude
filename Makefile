.DEFAULT_GOAL := help

.PHONY: help install lint test e2e book book-serve paper paper-figures clean changelog

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
paper:  ## Build the paper and stage it for the docs site (needs tectonic or pdflatex)
	cd paper && (tectonic $(PAPER).tex \
		|| (pdflatex -interaction=nonstopmode -halt-on-error $(PAPER).tex \
		    && pdflatex -interaction=nonstopmode -halt-on-error $(PAPER).tex))
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
