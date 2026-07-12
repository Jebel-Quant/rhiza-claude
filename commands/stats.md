---
description: Report a read-only statistics dashboard for the current repo — lines of code, lines of tests and their ratio, GitHub/GitLab stars, plus language mix, coverage, complexity, dependency counts, git activity, and rhiza template status. Runs the bundled scripts/stats.py (no data-gathering by the agent), which prints the dashboard and writes a self-contained docs/stats.html you can wire into mkdocs.yml. No scoring, no fixes, no issues.
argument-hint: "[path or topic to scope the stats to]  (optional; defaults to the whole repo)"
allowed-tools: Bash(python3*), Read
---

You are running `/stats` in the **current working directory's repo**.

**This command is a thin wrapper around the bundled `scripts/stats.py`.** All the
data-gathering, the terminal dashboard, and the `docs/stats.html` artifact live in
that script — a deterministic, stdlib-only Python program. Do **not** re-implement
any metric here or gather numbers yourself; run the script and relay its output.
Keeping the logic in one place is the whole point: the script is the single source
of truth, so the command can't drift from it as the template evolves.

Like the script, this is purely descriptive — it **counts and measures; it does not
score, fix, or file anything**. The only artifact written is `docs/stats.html`.
(Division of labour: `/quality` judges and scores; `/stats` just reports.)

Argument (optional): `$ARGUMENTS` — a path/pathspec to scope the code-size metrics
to (e.g. `src/foo`); default is the whole repo.

## 1. Run the script
Invoke it with the plugin-root path (it ships inside this plugin, so
`${CLAUDE_PLUGIN_ROOT}` resolves at runtime — **keep the quotes**):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/stats.py" $ARGUMENTS
```

- Pass `$ARGUMENTS` through as the optional `PATH` scope. If it's empty, just omit it.
- The script is read-only apart from writing `docs/stats.html`; it needs no network
  by default. Add flags only when the user asks:
  - `--slow` — permit slow/networked fallbacks (`uvx radon`/`interrogate`, `uv pip list --outdated`) so complexity/docstring/outdated metrics aren't `n/a`.
  - `--no-html` — skip writing the HTML artifact (terminal only).
  - `--html-out <path>` — write the HTML somewhere other than `docs/stats.html`.
- The script gathers all seven sections (identity, code size & language mix,
  tests & coverage, complexity, dependencies, git activity, rhiza template status),
  degrading any unavailable metric to `n/a (<reason>)` rather than failing.

## 2. If the script can't run
- If `${CLAUDE_PLUGIN_ROOT}` is empty (e.g. you're in a source checkout of this repo,
  not an installed plugin), fall back to the repo-relative path: `python3 scripts/stats.py $ARGUMENTS`.
- If `python3` is missing, or the script is genuinely not found at either path, report
  that plainly and stop — don't hand-roll the stats as a substitute.

## 3. Relay the results
- Show the script's terminal dashboard to the user as-is — it's already formatted
  (headline tiles, one-line summary, then the detailed sections). Don't re-derive or
  re-format the numbers.
- You may add **one short paragraph** of plain-language reading of the headline
  figures (LOC/test ratio, stars, issues, commits, rhiza freshness) — but **no scores
  and no recommendations**. If the user wants an assessment, point them at `/quality`.
- Surface the `docs/stats.html` line the script printed and the `mkdocs.yml` nav
  snippet it emits, so the user knows the artifact was written and how to wire it in.
  This command does **not** edit `mkdocs.yml`.
- If many metrics came back `n/a` because a tool wasn't on `PATH`, mention that
  `--slow` (or installing `scc`/`tokei`/`radon`/`interrogate`) would fill them in.
