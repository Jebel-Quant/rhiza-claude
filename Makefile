.DEFAULT_GOAL := help

.PHONY: help install lint test book book-serve paper paper-figures clean changelog

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

lint:  ## Run all pre-commit hooks against every file
	uvx pre-commit run --all-files

test:  ## Run the script test suite with a 100% coverage gate
	uvx --with pytest-cov pytest tests/ --cov=scripts --cov-report=term-missing \
		--cov-report=xml:$(TESTS)/coverage.xml \
		--cov-report=html:$(TESTS)/html-coverage \
		--cov-fail-under=100 $(ARGS)

# Individual quality checks (mypy, interrogate, test-layout, manifest validation)
# all run via `make lint` (pre-commit). For a single one, use e.g.
# `uvx pre-commit run mypy --all-files`.

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
