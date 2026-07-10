# rhiza-config

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CodeFactor](https://www.codefactor.io/repository/github/Jebel-Quant/rhiza-config/badge)](https://www.codefactor.io/repository/github/Jebel-Quant/rhiza-config)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Jebel-Quant/rhiza-config/badge)](https://scorecard.dev/viewer/?uri=github.com/Jebel-Quant/rhiza-config)
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/Jebel-Quant/rhiza-config)

Version-controlled [Claude Code](https://claude.com/claude-code) configuration
for `~/.claude`.

Only **authored** config is tracked here. Runtime state, session transcripts,
caches, logs, and secrets are deliberately kept out of version control via an
allowlist `.gitignore` (ignore everything, then un-ignore the few things worth
tracking).

## What's tracked

| Path | Purpose |
| --- | --- |
| `settings.json` | Shared Claude Code settings — model, permissions allowlist, TUI preferences. |
| `commands/` | Custom global slash commands (`/global_rhiza_boost`, `/global_rhiza_quality`, `/global_rhiza_revisit`, `/global_rhiza_stats`). |
| `scripts/` | Helper scripts invoked by commands (e.g. `rhiza_resolve.py`). |
| `.gitignore` | The allowlist that keeps everything else out. |

### Commands

- **`/global_rhiza_boost`** — bump the current repo to the latest (or a given)
  rhiza release, sync the template, resolve conflicts upstream, run the quality
  gates, and open a PR with a quality scorecard.
- **`/global_rhiza_quality`** — run the rhiza code-quality gate (lint, types,
  docs, deps, security, tests, complexity, architecture) and score the repo.
- **`/global_rhiza_revisit`** — create or revisit the current repo's `README.md`
  (with the full standard badge set), `CLAUDE.md`, and `mkdocs.yml`, preserving
  hand-written prose while refreshing badges and correcting drift.
- **`/global_rhiza_stats`** — read-only statistics dashboard for the current repo:
  lines of code/tests and their ratio, stars, open issues, PRs, branches, commits,
  releases, coverage, complexity, dependencies, and rhiza template status.

### Scripts

- **`scripts/rhiza_resolve.py`** — repo-agnostic helper that resolves
  rhiza-sync fallout by taking the upstream side of conflicts and `.rej` hunks.

## What's intentionally NOT tracked

Session transcripts (`history.jsonl`, `projects/`, `sessions/`), caches,
`file-history/`, `shell-snapshots/`, telemetry, daemon state, `backups/`, and
machine-local overrides (`settings.local.json`). These are per-machine runtime
data — noisy, large, and sometimes sensitive.

## Setup on a new machine

```bash
git clone git@github.com:Jebel-Quant/rhiza-config.git ~/.claude
```

> Clone into an **empty** `~/.claude`, or clone elsewhere and copy the tracked
> files in — Claude Code writes its runtime state into this same directory.

## Making changes

After editing any tracked file:

```bash
git add -A && git commit -m "..." && git push
```

Occasionally check `git status`: if a new authored directory appears (e.g.
`agents/`, `hooks/`), add a matching `!dir/` line to `.gitignore` to track it.
