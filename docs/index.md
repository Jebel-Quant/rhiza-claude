# rhiza-claude

A [Claude Code](https://claude.com/claude-code) plugin marketplace providing the
**`rhiza`** plugin — slash commands for working in
[rhiza](https://github.com/jebel-quant/rhiza)-managed repos: template sync,
code-quality scoring, and README/doc upkeep.

## Install

```
/plugin marketplace add Jebel-Quant/rhiza-claude
/plugin install rhiza@rhiza-claude
```

Or, from a shell:

```bash
make install
```

The commands appear namespaced under the plugin — type `/rhiza` to have Claude
Code autocomplete them.

## Commands

These are the AI-driven workflow commands. Each has its own page.

| Command | What it does |
| --- | --- |
| [`/rhiza:init`](commands/init.md) | Make the repo rhiza-managed: write `.rhiza/template.yml`, delegate the skeleton + license, open a PR. |
| [`/rhiza:update`](commands/update.md) | Sync to the latest template release and open a PR with **only** template-owned files. |
| [`/rhiza:quality`](commands/quality.md) | Run the code-quality gate and score the repo 1–10 across eight categories. |
| [`/rhiza:docs`](commands/docs.md) | Create or refresh `README.md`, `CLAUDE.md`, and `mkdocs.yml`. |
| [`/rhiza:release`](commands/release.md) | Prepare a release: pick the next version from a table, bump, changelog, commit, tag (no push). |

## Repo utilities

Thin, **read-only**, stdlib-only commands backed by bundled scripts — they read
`.rhiza/template.lock` / `.rhiza/template.yml` directly and work without the
`rhiza` CLI installed. Neither writes anything.

| Command | What it does |
| --- | --- |
| [`/rhiza:status`](commands/status.md) | Report both halves of the repo's rhiza state: is `template.yml` valid, and what did the last sync record. `--files` lists managed files as a tree; `--check` compares the pinned ref against the latest release. |
| [`/rhiza:maffay`](commands/maffay.md) | Return a bonmot from a random Peter Maffay song. Takes an optional theme keyword. Needs no repo at all. |

## Destructive

| Command | What it does |
| --- | --- |
| [`/rhiza:uninstall`](commands/uninstall.md) | Delete every rhiza-managed file listed in `.rhiza/template.lock`, prune the emptied directories, and remove the lock. Prompts for confirmation unless `--force` is passed. |

## Internals

Not slash commands. These are **internal procedures** in the plugin's `prompts/`
directory — deliberately outside `commands/` so they can't be invoked directly.
`/rhiza:init` and `/rhiza:update` read and follow them, and most are backed by a
deterministic, stdlib-only script under `scripts/`. Documented here because their
behaviour is part of what those commands do to your repo.

| Procedure | What it does | Script |
| --- | --- | --- |
| [install-uv](internals/install-uv.md) | Make sure `uv` is installed — the first step of both `/init` and `/update`. | — |
| [pr-base](internals/pr-base.md) | A work branch off an up-to-date default, which is never pushed to. | — |
| [skeleton](internals/skeleton.md) | `uv init --lib`, then the `[project]` shape the template's gates require. | `init_skeleton.py` |
| [license](internals/license.md) | SPDX `license`/`license-files` metadata + the `LICENSE` file. | `set_license.py` |
| [python-version](internals/python-version.md) | Pin `requires-python`, rewrite the Python classifiers, sync `.python-version`. | `set_python_version.py` |
| [design-analysis](internals/design-analysis.md) | Complexity and architecture evidence that no `make` gate measures. | — |
| [scorecard](internals/scorecard.md) | The 1–10 rubric, the scoping rule, findings and the issue menu. | — |
