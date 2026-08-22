## Makefile (repo-owned) -- the shim shape rhiza's `core` bundle ships, hand-copied.
#
# **This repo is the plugin, not a rhiza-managed repo.** There is no `.rhiza/`, so nothing
# syncs this file and the "edit it in the template" instruction the real shim carries would
# be false here. It is a copy, kept close to the original on purpose: rhiza-claude is where
# that shape is designed, so dogfooding it is how the next change to it gets reviewed
# against a repo someone actually runs.
#
# The division of labour is the original's. This file owns the front door -- `.DEFAULT_GOAL`,
# `help`, the uv bootstrap and the delegation catch-all. Every target this repo actually
# runs lives in `local.mk`, which is `-include`d at the bottom, and an explicit rule beats
# a pattern rule, so those win over delegation.
RHIZA_TASK ?= rhiza-task@1.1.0

# uv cannot be delegated, because uv is what runs the CLI. Prepended so a machine carrying
# an older uv still resolves the pin, exported because task bodies shell out to bare `uv`.
INSTALL_DIR ?= $(abspath ./bin)
UVX ?= $(shell command -v uvx 2>/dev/null || echo $(INSTALL_DIR)/uvx)
export PATH := $(INSTALL_DIR):$(PATH)

# `UV` too, for `local.mk` to reach: the astral installer writes both binaries into the
# same directory, so once $(UVX) exists this does, and the empty recipe both satisfies
# make's remake attempt and keeps the catch-all from forwarding the path as a task name.
UV ?= $(shell command -v uv 2>/dev/null || echo $(INSTALL_DIR)/uv)
$(UV): $(UVX) ;

.DEFAULT_GOAL := help

.PHONY: help

# **This repo delegates nothing**, so unlike the template's shim there is no
# `rhiza-task list` above this: every target it has is in `local.mk` and carries a `##`
# comment. Listing the CLI's catalogue as well would advertise some forty tasks that do
# not apply -- `install` there is `uv sync` against a `pyproject.toml` this repo
# deliberately does not have, and the scoped gates would resolve `source-folder` to a
# `src/` that does not exist.
#
# Note the `0-9` in the class. The old hand-rolled help used `^[a-zA-Z_-]+`, so `e2e:` never
# matched and the target was missing from `make help` while being fully documented.
help:
	@own=$$(grep -hE '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | sed -e 's/:.*##/ -- /' -e 's/^/  /'); \
		[ -z "$$own" ] || printf 'Targets:\n%s\n' "$$own"

# Every task, and every typo -- the CLI's "unknown task" error is the backstop. `FORCE` is
# what keeps them phony: .PHONY takes no patterns, but a phony prerequisite is never up to
# date, so `make book` next to a `book/` directory still runs. Recursive `=` because `$@`
# only has a value while make is running the rule.
RHIZA_TASK_GOAL = $@

%: $(UVX) FORCE
	@$(UVX) $(RHIZA_TASK) $(RHIZA_TASK_GOAL)

# A file target, so make's up-to-date check is the idempotence. `$(UVX)` and not
# `$(INSTALL_DIR)/uvx`, because an on-PATH uvx would otherwise be matched by the catch-all
# whose prerequisite is that same file: `make: Circular ... dependency dropped`.
$(UVX):
	@echo "[INFO] uv not found; installing into $(@D)"
	@curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR="$(@D)" sh >/dev/null

.PHONY: FORCE
FORCE:

# Repo-specific one-offs. An explicit rule beats a pattern rule, so these win.
-include local.mk

# Both are targets make tries to remake, and the catch-all would route that to the CLI.
local.mk: ;
Makefile: ;
