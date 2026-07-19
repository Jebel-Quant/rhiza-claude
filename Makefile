.DEFAULT_GOAL := help

.PHONY: help install lint test stats book book-serve clean changelog release

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

stats:  ## Print the repo statistics dashboard + write docs/stats.html
	uv run --python 3.12 --no-project python scripts/stats.py $(ARGS)

book:  ## Build the documentation site into _book/
	uvx --with mkdocs-material mkdocs build --strict

book-serve:  ## Serve the docs locally with live reload
	uvx --with mkdocs-material mkdocs serve

clean:  ## Remove generated caches and artifacts (ruff cache, __pycache__, docs/stats.html, _book)
	rm -rf .ruff_cache _book
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -f docs/stats.html

changelog:  ## Regenerate CHANGELOG.md from conventional commits
	uvx git-cliff --output CHANGELOG.md

release:  ## Prepare a release: make release VERSION=vX.Y.Z
	@test -n "$(VERSION)" || { echo "usage: make release VERSION=vX.Y.Z"; exit 1; }
	@bash scripts/release.sh "$(VERSION)"
