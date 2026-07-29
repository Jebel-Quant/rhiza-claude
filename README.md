# rhiza-claude

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Jebel-Quant/rhiza-claude/badge)](https://scorecard.dev/viewer/?uri=github.com/Jebel-Quant/rhiza-claude)

A [Claude Code](https://claude.com/claude-code) plugin marketplace providing the
**`rhiza`** plugin — slash commands for working in rhiza-managed repos (template
sync, code-quality scoring, and README/doc upkeep).

📖 **Documentation:** <https://jebel-quant.github.io/rhiza-claude/> — a dedicated
page for every command. Build it locally with `make book`.

## Install

```
/plugin marketplace add Jebel-Quant/rhiza-claude
/plugin install rhiza@rhiza-claude
```

Or, from a shell, `make install` runs the equivalent `claude` CLI commands:

```bash
make install
```

The commands then appear namespaced under the plugin: `/rhiza:init`,
`/rhiza:update`, `/rhiza:quality`, `/rhiza:docs`. Type `/rhiza`
to have Claude Code autocomplete them.

### Install a specific version

By default the marketplace tracks this repo's default branch, so `/plugin
install` pulls the latest release. To pin to a specific published version,
append that version's git tag as a `#<ref>` suffix when you add the marketplace
(see the [releases page](https://github.com/Jebel-Quant/rhiza-claude/releases)
for available tags):

```
/plugin marketplace add Jebel-Quant/rhiza-claude#v0.4.1
/plugin install rhiza@rhiza-claude
```

The same `#<ref>` suffix works from a shell:

```bash
claude plugin marketplace add Jebel-Quant/rhiza-claude#v0.4.1
claude plugin install rhiza@rhiza-claude
```

Pinning happens at the marketplace layer, not per plugin — once the marketplace
is added, `/plugin install` uses whatever ref it points at. To switch versions,
remove the marketplace and re-add it at the desired tag:

```
/plugin marketplace remove rhiza-claude
/plugin marketplace add Jebel-Quant/rhiza-claude#v0.4.0
```

## Prerequisites

The commands drive a rhiza-managed repo with [`uv`](https://docs.astral.sh/uv/) —
install it once:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

You don't have to do this ahead of time, though: both `/rhiza:init` and
`/rhiza:update` check for `uv` as their first step and offer to install it (with your
approval) on any platform. `git` and `make` are also used but are near-universal, and
the plugin's own bundled scripts are stdlib-only Python — no `rhiza` CLI required.

## Commands

- **`/rhiza:init`** — make the current folder rhiza-managed. It writes **one file**
  itself — `.rhiza/template.yml`, the pointer at a template repo and pinned ref — and
  delegates the rest to the internal procedures (see [Internals](#internals)):
  install-uv, then skeleton, then license. It detects platform/owner/name from an
  existing `origin` (or asks), picks the language (Python or Go) and template repo
  (`jebel-quant/rhiza` / `rhiza-go`, or a custom one) plus its latest release as the
  initial pin, and opens a PR on a `rhiza_init_<date>` branch — never pushing to the
  default branch (a brand-new repo's base branch is created by you). It runs **no
  sync and no gates**: the template content (CI, `Makefile`, `rhiza.mk`, docs base)
  arrives when you run `/rhiza:update` after the PR merges — a second PR.
- **`/rhiza:update`** — sync the repo to the latest (or a given) template release:
  bump the `ref` in `.rhiza/template.yml`, run the bundled sync, resolve conflicts by
  taking the upstream side, and open a PR containing **only template-owned files** —
  the paths `.rhiza/template.lock` records, never a blanket `git add --all`, so your
  own source is never swept in. The template repo is read from `template.yml`, so
  forks and `rhiza-go` work too. Runs no gates and files no issues: use
  `/rhiza:quality` for a scorecard.
- **`/rhiza:quality`** — run the rhiza code-quality gate (lint, types, docs,
  deps, security, tests, complexity, architecture) and score the repo.
- **`/rhiza:docs`** — create or refresh the repo's three top-of-repo documentation
  files: `README.md` (with the standard badge set), `CLAUDE.md`, and `mkdocs.yml`.
  Detects platform, owner/repo and project metadata at runtime, preserves hand-written
  prose, and keeps the README's `make help` target list in lockstep with the real
  `Makefile`. Badges are generated with **omit, don't fake** — a badge whose backing
  fact isn't detected is never emitted. Writes files only; no commit, no PR.
- **`/rhiza:release`** — prepare a release locally: **table up the legal next versions**
  and let you pick (it never suggests or defaults to one), **guard that the choice
  strictly increases** past every prior release, then let `bump-my-version` write it into every
  location the repo declares in `[tool.bumpversion]` — `pyproject.toml`, plugin
  manifests, self-referencing CI stub pins — regenerate `CHANGELOG.md`, and commit and
  tag. Because the locations are declared rather than inferred, a dependency that
  happens to share the version number is never rewritten. Stops before pushing; pushing
  the tag is what triggers the release CI.

### Internals

Not slash commands. These are **internal procedures** under `prompts/` —
deliberately outside `commands/` so they can't be invoked directly. `/rhiza:init` and
`/rhiza:update` read and follow them, and most are backed by a deterministic,
stdlib-only script.

- **install-uv** (`prompts/install-uv.md`) — make sure `uv`, the plugin's one hard
  dependency, is installed, via the official astral.sh installer, Homebrew, or
  winget. Never installs without approval; sorts out the `PATH` step the installer
  leaves behind. The **first step of both `/rhiza:init` and `/rhiza:update`**.
- **pr-base** (`prompts/pr-base.md`) — a work branch based on an up-to-date remote
  default branch, which is **never pushed to**: when it doesn't exist yet, *you* create
  the repo with an empty README rather than the command pushing one. Shared by
  `/rhiza:init` and `/rhiza:update`, so both behave identically.
- **skeleton** (`prompts/skeleton.md` → `scripts/init_skeleton.py`) — `uv init --lib`
  when there's no `pyproject.toml`, then the shape the template's gates require: a
  package docstring in place of uv's `hello()` placeholder, the description, and the
  `[project.urls]` and `[dependency-groups]` entries the synced pyproject gate
  asserts. Idempotent and additive. The template never ships a `pyproject.toml`, so
  the quality gates need this to have run.
- **license** (`prompts/license.md` → `scripts/set_license.py`) — the SPDX
  `license`/`license-files` metadata in `pyproject.toml` plus the `LICENSE` file's
  full text (MIT, Apache-2.0, BSD-3-Clause bundled). Overwriting an existing
  `LICENSE` needs `--force`; `none` clears the metadata. Never writes a deprecated
  `License ::` trove classifier.
- **design-analysis** (`prompts/design-analysis.md`) — the complexity and architecture
  evidence no `make` gate measures: radon CC/MI, module sizes, the import graph, layering
  direction, and cycles including ones hidden behind function-local imports. Gathers
  evidence; doesn't judge.
- **scorecard** (`prompts/scorecard.md`) — the 1–10 rubric: the subcategory list, the
  coverage bar, the findings format, the issue menu, and the **scoping rule** that stops
  a managed repo being marked down for its own template.
- **python-version** (`prompts/python-version.md` → `scripts/set_python_version.py`)
  — pin `requires-python` and rewrite the `Programming Language :: Python :: X.Y`
  classifiers to the supported range (3.11–3.14; never a bare `:: 3`), and sync
  `.python-version`.

### Repo utilities

Thin, **read-only**, stdlib-only commands backed by bundled scripts — they read
`.rhiza/template.lock` / `.rhiza/template.yml` directly and work without the `rhiza`
CLI installed. Neither writes anything.

- **`/rhiza:status`** — report both halves of the repo's rhiza state: whether
  `.rhiza/template.yml` is valid (what you'd sync *from*), and what
  `.rhiza/template.lock` records as actually synced (repository, ref, SHA, timestamp,
  strategy). They can disagree in both directions, so reporting one alone misleads.
  Add `--files` (alias `--tree`) to list the managed files as a directory tree, or
  `--check` to compare the pinned ref against the latest upstream release.
  Read-only.
### Destructive

- **`/rhiza:uninstall`** — delete every rhiza-managed file listed in
  `.rhiza/template.lock`, prune the emptied directories, and remove the lock. This is
  the only command that removes files wholesale; it prompts for confirmation unless
  `--force` is passed.

## Layout

| Path | Purpose |
| --- | --- |
| `.claude-plugin/marketplace.json` | Marketplace manifest listing the `rhiza` plugin. |
| `.claude-plugin/plugin.json` | The `rhiza` plugin manifest. |
| `commands/` | The plugin's slash commands (one `.md` per command). |
| `prompts/` | Internal procedures the commands `Read` — deliberately not commands, so users can't invoke them. |
| `scripts/` | Bundled stdlib-only Python the commands and procedures drive. |

## Contributing

Edit the command `.md` files under `commands/`, then commit and push:

```bash
git add -A && git commit -m "..." && git push
```

Installed users pick up changes the next time the marketplace refreshes.
