## local.mk (repo-owned) -- every target this repo actually runs, `-include`d by the Makefile.
#
# The `Makefile` beside this file is the shim shape rhiza's `core` bundle ships: it owns the
# front door and delegates any unknown target to `rhiza-task`. Nothing here delegates. An
# explicit rule beats the shim's `%:` pattern rule, so every target below wins over the
# catch-all, and the `##` comments are what put it in `make help`.
#
# **Why none of this can move to the CLI.** rhiza-claude is the plugin, not a rhiza-managed
# repo, and it has no `pyproject.toml` to hold `[tool.rhiza-task]`. Ask the CLI what it would
# measure here and it answers with its own defaults -- `rhiza-task print source-folder` says
# `src`, which does not exist in this repo, and `typechecker` says `ty`, where this repo
# gates `mypy --strict`. Delegating `test` would drop the `--cov=plugin/scripts
# --cov-fail-under=100` floor; delegating the scoped gates would reproduce rhiza's own
# #1505/#1511/#1516, where five gates exited 0 having measured nothing. These gates are this
# repo's, and they stay this repo's.
#
# `$(UVX)` comes from the shim, which provisions uv on demand. It is a prerequisite on every
# target that shells out to `uvx` so a machine without uv bootstraps one, rather than failing
# with "command not found" partway through a recipe.

.PHONY: install audit complexity e2e portable paper-figures clean

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

install:  ## Install the rhiza plugin via the Claude Code CLI
	claude plugin marketplace add $(MARKETPLACE)
	claude plugin install $(PLUGIN)

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
audit: $(UVX)  ## Security-audit the bundled scripts (bandit) and the workflows (zizmor)
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
complexity: $(UVX)  ## Report cyclomatic complexity and maintainability index (the census CLAUDE.md quotes)
	uvx radon cc plugin/scripts -s -n C --total-average
	uvx radon cc tests -s -n C --total-average
	uvx radon mi plugin/scripts -s

# PyYAML is a *test* dependency only — the bundled scripts stay stdlib-only at runtime.
# It is here so the PyYAML arm of `_rhiza_yaml.load_yaml` is exercised and measured:
# with it absent, half of that module's behaviour was invisible to the coverage gate.
#
# One definition of the runner, shared by `e2e` and `portable`. The `--with` flags are the
# part that has drifted before: CI once hand-wrote this command line, the Makefile gained
# `--with pyyaml`, and the copy in CI did not — so that arm went unmeasured on a branch
# that was green locally. Anything that runs this suite goes through a target here.
PYTEST := uvx --with pytest-cov --with pyyaml pytest tests/

# The end-to-end subset on its own — the tests that clone the real template and drive the
# command chains against a genuinely synced repo. `make test` runs these too; this target
# exists for the one caller that needs them *without* the coverage gate, the weekly
# template-drift job, since a filtered run cannot reach 100% and coverage is not the
# question it asks. Not a substitute for `make test`: it reports no coverage at all, so a
# green `make e2e` says nothing about the gate every other caller has to clear.
e2e: $(UVX)  ## Run only the end-to-end tests, without the coverage gate
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
portable: $(UVX)  ## Run the unit tests without e2e or the coverage gate (the cross-platform CI subset)
	$(PYTEST) -k "not e2e" --no-cov $(ARGS)

# Individual quality checks (mypy, interrogate, test-layout, manifest validation)
# all run via `make lint` (prek). For a single one, use e.g.
# `uvx prek run mypy --all-files`.

paper-figures: $(UVX)  ## Regenerate the paper's figures from the captured command output
	uv run --with pillow python paper/render_figures.py

clean:  ## Remove generated caches and artifacts (ruff cache, __pycache__, _book, test reports, paper build)
	rm -rf .ruff_cache _book $(TESTS) docs/reports docs/paper
	rm -f paper/*.aux paper/*.log paper/*.out paper/*.pdf
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
