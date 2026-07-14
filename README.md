# rhiza-claude

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Jebel-Quant/rhiza-claude/badge)](https://scorecard.dev/viewer/?uri=github.com/Jebel-Quant/rhiza-claude)

A [Claude Code](https://claude.com/claude-code) plugin marketplace providing the
**`rhiza`** plugin — slash commands for working in rhiza-managed repos (template
sync, code-quality scoring, README/doc upkeep, and repo stats).

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

The commands then appear namespaced under the plugin: `/rhiza:install`,
`/rhiza:update`, `/rhiza:quality`, `/rhiza:revisit`, `/rhiza:stats`,
`/rhiza:repos`. Type `/rhiza` to have Claude Code autocomplete them.

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

## Commands

- **`/rhiza:install`** — bootstrap a rhiza-managed repo in the current folder
  (empty, or an existing git repo that isn't managed yet): `git init` if
  needed, ask whether it lives on GitHub or GitLab, ask owner/name/visibility,
  pick the language (Python or Go) and template repo (`jebel-quant/rhiza` /
  `rhiza-go`, or a custom one), optionally scaffold the project (`pyproject.toml`
  + `src/` + `tests/`, `mkdocs.yml`, a starter `README.md`), validate the config,
  then put the scaffold and the first template sync on a `rhiza_install_<date>`
  branch and open a PR — never pushing rhiza changes straight to the default
  branch.
- **`/rhiza:update`** — bump the current repo to the latest (or a given) rhiza
  release, sync the template, resolve conflicts upstream, run the quality gates,
  and open a PR with a quality scorecard.
- **`/rhiza:quality`** — run the rhiza code-quality gate (lint, types, docs,
  deps, security, tests, complexity, architecture) and score the repo.
- **`/rhiza:revisit`** — create or revisit the current repo's `README.md` (with
  the full standard badge set), `CLAUDE.md`, and `mkdocs.yml`, preserving
  hand-written prose while refreshing badges and correcting drift.
- **`/rhiza:stats`** — read-only statistics dashboard for the current repo:
  lines of code/tests and their ratio, stars, open issues, PRs, branches,
  commits, releases, coverage, complexity, dependencies, and rhiza template
  status.
- **`/rhiza:repos`** — list the GitHub repositories tagged with a rhiza topic
  (default `rhiza`) as a JSON document — name, description, URL, topics,
  language, stars, and timestamps. Set `GITHUB_TOKEN` to raise the API rate
  limit.
- **`/rhiza:release`** — prepare a release for the current rhiza-managed repo:
  derive the next semantic version from the conventional commits since the last
  tag (via git-cliff, overridable), bump `pyproject.toml`, regenerate
  `CHANGELOG.md`, then commit and tag locally. Stops before pushing — it prints
  the push commands, and pushing the tag is what triggers the release CI.

## Layout

| Path | Purpose |
| --- | --- |
| `.claude-plugin/marketplace.json` | Marketplace manifest listing the `rhiza` plugin. |
| `.claude-plugin/plugin.json` | The `rhiza` plugin manifest. |
| `commands/` | The plugin's slash commands (one `.md` per command). |

## Contributing

Edit the command `.md` files under `commands/`, then commit and push:

```bash
git add -A && git commit -m "..." && git push
```

Installed users pick up changes the next time the marketplace refreshes.
