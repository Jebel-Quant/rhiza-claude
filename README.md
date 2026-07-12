# rhiza-config

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A [Claude Code](https://claude.com/claude-code) plugin marketplace providing the
**`rhiza`** plugin — slash commands for working in rhiza-managed repos (template
sync, code-quality scoring, README/doc upkeep, and repo stats).

📖 **Documentation:** <https://jebel-quant.github.io/rhiza-config/> — a dedicated
page for every command. Build it locally with `make book`.

## Install

```
/plugin marketplace add Jebel-Quant/rhiza-config
/plugin install rhiza@rhiza-config
```

Or, from a shell, `make install` runs the equivalent `claude` CLI commands:

```bash
make install
```

The commands then appear namespaced under the plugin: `/rhiza:init`,
`/rhiza:boost`, `/rhiza:quality`, `/rhiza:revisit`, `/rhiza:stats`,
`/rhiza:repos`. Type `/rhiza` to have Claude Code autocomplete them.

## Commands

- **`/rhiza:init`** — bootstrap a rhiza-managed repo in the current folder
  (empty, or an existing git repo that isn't managed yet): `git init` if
  needed, ask whether it lives on GitHub or GitLab, ask owner/name/visibility,
  pick the language (Python or Go) and template repo (`jebel-quant/rhiza` /
  `rhiza-go`, or a custom one), optionally scaffold the project (`pyproject.toml`
  + `src/` + `tests/`, `mkdocs.yml`, a starter `README.md`), validate the config,
  then put the scaffold and the first template sync on a `rhiza_init_<date>`
  branch and open a PR — never pushing rhiza changes straight to the default
  branch.
- **`/rhiza:boost`** — bump the current repo to the latest (or a given) rhiza
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
