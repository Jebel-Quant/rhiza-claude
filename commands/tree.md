---
description: List the files rhiza manages in this repo as a directory tree, then a total count — read from .rhiza/template.lock. Runs the bundled scripts/tree.py (a stdlib-only read of the lock), so it works without the rhiza CLI installed. Read-only; no scoring, no fixes, no issues.
argument-hint: "[path to a repo root]  (optional; defaults to the current repo)"
allowed-tools: Bash(python3*), Read
---

You are running `/tree` in the **current working directory's repo**.

**This command is a thin wrapper around the bundled `scripts/tree.py`.** All the
lock-reading and tree rendering lives in that script — a deterministic, stdlib-only
Python program that reads `.rhiza/template.lock` directly (no `rhiza` CLI, no
PyYAML required). Do **not** re-implement the parsing or build the tree yourself;
run the script and relay its output.

This is purely descriptive — it **lists what's managed; it does not score, fix, or
file anything**.

Argument (optional): `$ARGUMENTS` — a path to the repo root to inspect; default
is the current directory.

## 1. Run the script
Invoke it with the plugin-root path (it ships inside this plugin, so
`${CLAUDE_PLUGIN_ROOT}` resolves at runtime — **keep the quotes**):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tree.py" $ARGUMENTS
```

- Pass `$ARGUMENTS` through as the optional target path. If it's empty, just omit it.

## 2. If the script can't run
- If `${CLAUDE_PLUGIN_ROOT}` is empty (e.g. you're in a source checkout of this repo,
  not an installed plugin), fall back to the repo-relative path: `python3 scripts/tree.py $ARGUMENTS`.
- If `python3` is missing, or the script is genuinely not found at either path, report
  that plainly and stop — don't hand-roll the tree as a substitute.

## 3. Relay the results
- Show the script's tree output as-is — it's already formatted, ending with the
  file count.
- If it printed `No template.lock found`, the repo hasn't been synced yet: tell the
  user to run `rhiza sync` first. This is not an error.
- No scores or recommendations. For a fuller dashboard, point them at `/stats`; for
  the sync metadata behind this file list, `/status`.
