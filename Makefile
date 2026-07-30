.DEFAULT_GOAL := help

.PHONY: help install lint test book book-serve paper paper-figures clean changelog

PAPER := rhiza-claude-intro

MARKETPLACE := Jebel-Quant/rhiza-claude
PLUGIN := rhiza@rhiza-claude

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install the rhiza plugin via the Claude Code CLI
	claude plugin marketplace add $(MARKETPLACE)
	claude plugin install $(PLUGIN)

lint:  ## Run all pre-commit hooks against every file
	uvx pre-commit run --all-files

test:  ## Run the script test suite with a 100% coverage gate
	uvx --with pytest-cov pytest tests/ --cov=scripts --cov-report=term-missing --cov-fail-under=100 $(ARGS)

# Individual quality checks (mypy, interrogate, test-layout, manifest validation)
# all run via `make lint` (pre-commit). For a single one, use e.g.
# `uvx pre-commit run mypy --all-files`.

# The book depends on the paper: docs/index.md links the PDF, and `--strict` fails on a
# link whose target is missing. Building the paper on every book build is also what keeps
# the .tex honest — a commit that breaks it fails CI rather than shipping a stale PDF.
book: paper  ## Build the documentation site into _book/ (compiles the paper first)
	uvx --with mkdocs-material mkdocs build --strict

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

clean:  ## Remove generated caches and artifacts (ruff cache, __pycache__, _book, paper build)
	rm -rf .ruff_cache _book docs/paper
	rm -f paper/*.aux paper/*.log paper/*.out paper/*.pdf
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

changelog:  ## Regenerate CHANGELOG.md from conventional commits
	uvx git-cliff --output CHANGELOG.md
