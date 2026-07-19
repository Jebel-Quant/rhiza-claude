---
description: Remove all rhiza-managed files from the repo — deletes every file listed in .rhiza/template.lock, prunes the emptied directories, and removes the lock file itself. Runs the bundled scripts/uninstall.py (stdlib-only). DESTRUCTIVE; prompts for confirmation unless --force is passed.
argument-hint: "[path to a repo root]  (optional; defaults to the current repo)"
allowed-tools: Bash(uv*), Bash(python3*), Read
---

You are running `/uninstall` in the **current working directory's repo**.

**This command is a thin wrapper around the bundled `scripts/uninstall.py`.** All
the deletion logic lives in that script — a deterministic, stdlib-only Python
program that reads `.rhiza/template.lock` directly (no `rhiza` CLI, no PyYAML
required). Do **not** re-implement it or delete files yourself; run the script.

⚠️ **This is destructive.** It permanently deletes the files rhiza synced into the
repo, removes the directories they leave empty, and deletes `.rhiza/template.lock`
so the repo is no longer rhiza-managed. Files you added yourself are untouched.

Argument (optional): `$ARGUMENTS` — a path to the repo root to clean; default is
the current directory.

## 1. Confirm intent first
Because this deletes files, **confirm with the user before running** unless they
have already clearly asked to proceed (e.g. said "yes, uninstall" or passed
`--force`). Recommend they have a clean git tree / committed work first, so the
deletion is easy to review and revert.

## 2. Run the script
Invoke it with the plugin-root path (it ships inside this plugin, so
`${CLAUDE_PLUGIN_ROOT}` resolves at runtime — **keep the quotes**):

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/uninstall.py" $ARGUMENTS --force
```

- Pass `$ARGUMENTS` through as the optional target path. If it's empty, just omit it.
- The script normally prompts `[y/N]` for confirmation. When run non-interactively
  (as here, with no TTY to answer) an unanswered prompt is treated as "no" and it
  cancels — so pass `--force` (equivalently `-y`) **only after** the user has
  confirmed in step 1, to carry out the deletion they approved.

## 3. If the script can't run
- If `${CLAUDE_PLUGIN_ROOT}` is empty (e.g. you're in a source checkout of this repo,
  not an installed plugin), fall back to the repo-relative path: `uv run --python 3.12 --no-project python scripts/uninstall.py $ARGUMENTS --force`.
- If `uv` is missing, or the script is genuinely not found at either path, report
  that plainly and stop — never hand-roll the deletions as a substitute.

## 4. Relay the results
- Show the script's output as-is — it prints each `[DEL]` line and an uninstall
  summary (files removed / skipped / empty dirs removed / errors).
- The script exits **0 on success or a clean no-op, 1 if any deletion failed**. If it
  exited 1, surface the error lines.
- If it reported `No lock file found` or `Nothing to uninstall`, the repo wasn't
  rhiza-managed — say so; it's not an error.
- Afterwards, point the user at the printed next steps: review with `git status` /
  `git diff`, then commit the removal.
