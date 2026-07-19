---
description: Show the current rhiza sync status for the repo — the template repository, ref, synced commit SHA, sync timestamp, strategy, and the templates/paths that were materialized. Runs the bundled scripts/status.py (a stdlib-only read of .rhiza/template.lock), so it works without the rhiza CLI installed. Read-only; no scoring, no fixes, no issues.
argument-hint: "[path to a repo root]  (optional; defaults to the current repo)"
allowed-tools: Bash(uv*), Bash(python3*), Read
---

You are running `/status` in the **current working directory's repo**.

**This command is a thin wrapper around the bundled `scripts/status.py`.** All the
lock-reading and formatting lives in that script — a deterministic, stdlib-only
Python program that reads `.rhiza/template.lock` directly (no `rhiza` CLI, no
PyYAML required). Do **not** re-implement the parsing or gather the fields
yourself; run the script and relay its output. Keeping the logic in one place is
the point: the script is the single source of truth.

This is purely descriptive — it **reports the recorded sync state; it does not
score, fix, or file anything**.

Argument (optional): `$ARGUMENTS` — a path to the repo root to inspect; default
is the current directory.

## 1. Run the script
Invoke it with the plugin-root path (it ships inside this plugin, so
`${CLAUDE_PLUGIN_ROOT}` resolves at runtime — **keep the quotes**):

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" $ARGUMENTS
```

- Pass `$ARGUMENTS` through as the optional target path. If it's empty, just omit it.
- Add `--json` only when the user wants machine-readable output; the default is
  the human-readable summary.
- Add `--files` (alias `--tree`) when the user wants the managed files listed as
  a directory tree beneath the summary — this is the view the retired
  `/rhiza:tree` command used to give. `--json` already includes the `files`
  array, so `--files` only affects the human-readable output.
- Add `--check` when the user wants to know whether the template is behind: it
  compares the pinned `ref` to the latest upstream release (via
  `git ls-remote --tags`, no `gh` or auth needed) and prints an `Update` line —
  e.g. `v1.0.0 → v1.2.0 (2 releases behind) — run /update`, or `up to date`.
  This is the **only** part of `/status` that needs network; a git/network
  failure is reported, never fatal. For actually applying the bump, point the
  user at `/update`.

## 2. If the script can't run
- If `${CLAUDE_PLUGIN_ROOT}` is empty (e.g. you're in a source checkout of this repo,
  not an installed plugin), fall back to the repo-relative path: `uv run --python 3.12 --no-project python scripts/status.py $ARGUMENTS`.
- If `uv` is missing, or the script is genuinely not found at either path, report
  that plainly and stop — don't hand-roll the status as a substitute.

## 3. Relay the results
- Show the script's output as-is — it's already formatted.
- If it printed `No template.lock found`, the repo hasn't been synced yet: tell the
  user to run `rhiza sync` first. This is not an error.
- You may add **one short line** noting how fresh the sync looks (ref + synced-at),
  but **no scores and no recommendations**. For an assessment, point them at `/quality`;
  for a fuller dashboard, `/stats`.
