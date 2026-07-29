.DEFAULT_GOAL := help

.PHONY: help install lint test book book-serve paper clean changelog

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

book:  ## Build the documentation site into _book/
	uvx --with mkdocs-material mkdocs build --strict

book-serve:  ## Serve the docs locally with live reload
	uvx --with mkdocs-material mkdocs serve

paper:  ## Build paper/rhiza-claude-intro.pdf (needs tectonic or pdflatex)
	cd paper && (tectonic rhiza-claude-intro.tex || pdflatex -interaction=nonstopmode rhiza-claude-intro.tex)

clean:  ## Remove generated caches and artifacts (ruff cache, __pycache__, _book, paper build)
	rm -rf .ruff_cache _book
	rm -f paper/*.aux paper/*.log paper/*.out paper/*.pdf
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

changelog:  ## Regenerate CHANGELOG.md from conventional commits
	uvx git-cliff --output CHANGELOG.md
