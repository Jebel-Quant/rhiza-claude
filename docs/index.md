# rhiza-claude

A [Claude Code](https://claude.com/claude-code) plugin marketplace providing the
**`rhiza`** plugin — slash commands for working in
[rhiza](https://github.com/jebel-quant/rhiza)-managed repos: template sync,
code-quality scoring, README/doc upkeep, and repo stats.

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
| [`/rhiza:install`](commands/install.md) | Bootstrap a rhiza-managed repo from scratch: git init, platform choice, scaffold, first sync, PR. |
| [`/rhiza:update`](commands/update.md) | Bump to the latest rhiza release, sync, run the quality gates, open a scorecard PR. |
| [`/rhiza:quality`](commands/quality.md) | Run the code-quality gate and score the repo 1–10 across eight categories. |
| [`/rhiza:revisit`](commands/revisit.md) | Create or refresh `README.md`, `CLAUDE.md`, and `mkdocs.yml`. |
| [`/rhiza:stats`](commands/stats.md) | A read-only statistics dashboard for the repo. |
| [`/rhiza:repos`](commands/repos.md) | List the GitHub repos tagged with a rhiza topic as JSON. |
| [`/rhiza:new`](commands/new.md) | Scaffold a new source module + its mirrored test, keeping layout parity. |

## Repo utilities

Thin, **stdlib-only** commands backed by bundled scripts — they read
`.rhiza/template.lock` / `.rhiza/template.yml` directly and work without the
`rhiza` CLI installed.

| Command | What it does |
| --- | --- |
| [`/rhiza:status`](commands/status.md) | Show the current sync status (template, ref, SHA, timestamp). |
| [`/rhiza:tree`](commands/tree.md) | List the files rhiza manages, as a directory tree. |
| [`/rhiza:validate`](commands/validate.md) | Validate `.rhiza/template.yml`. |
| [`/rhiza:uninstall`](commands/uninstall.md) | Remove all rhiza-managed files (destructive). |
