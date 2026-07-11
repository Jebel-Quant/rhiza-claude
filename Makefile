.DEFAULT_GOAL := help

.PHONY: help lint validate changelog release

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

lint:  ## Run all pre-commit hooks against every file
	uvx pre-commit run --all-files

validate:  ## Validate the plugin manifests (JSON + version parity)
	@python3 -c "import json; json.load(open('.claude-plugin/plugin.json')); json.load(open('.claude-plugin/marketplace.json')); print('JSON OK')"
	@python3 scripts/check_version_parity.py

changelog:  ## Regenerate CHANGELOG.md from conventional commits
	uvx git-cliff --output CHANGELOG.md

release:  ## Prepare a release: make release VERSION=vX.Y.Z
	@test -n "$(VERSION)" || { echo "usage: make release VERSION=vX.Y.Z"; exit 1; }
	@bash scripts/release.sh "$(VERSION)"
