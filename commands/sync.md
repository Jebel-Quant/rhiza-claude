---
description: Sync the rhiza template into this repo — clone the upstream template, 3-way-merge upstream changes onto the working tree (preserving local edits), update .rhiza/template.lock, and clean up orphaned files. Runs the bundled scripts/sync.py (a stdlib-only port of `rhiza sync`), so it works without the rhiza CLI installed. Mutates the working tree; leaves conflict markers to resolve on collision.
argument-hint: "[path to a repo root]  (optional; defaults to the current repo)"
allowed-tools: Bash(python3*), Bash(git*), Read
---

You are running `/sync` in the **current working directory's repo**.

**This command is a thin wrapper around the bundled `scripts/sync.py`.** All the
cloning, diffing, 3-way merge, lock writing, and orphan cleanup live in that
script — a deterministic, stdlib-only port of `rhiza sync` that shells out to
`git` and needs neither the `rhiza` CLI nor PyYAML. Do **not** re-implement any of
it; run the script and relay its output.

**This command mutates the working tree** (unlike the read-only `/status`,
`/tree`, `/stats`). It requires a **clean working tree** and `git` on `PATH`.

Argument (optional): `$ARGUMENTS` — a path to the repo root to sync; default is
the current directory.

## 1. Run the script
Invoke it with the plugin-root path (it ships inside this plugin, so
`${CLAUDE_PLUGIN_ROOT}` resolves at runtime — **keep the quotes**):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sync.py" $ARGUMENTS
```

- Pass `$ARGUMENTS` through as the optional target path. If it's empty, just omit it.

## 2. If the script can't run
- If `${CLAUDE_PLUGIN_ROOT}` is empty (e.g. you're in a source checkout of this
  repo, not an installed plugin), fall back to the repo-relative path:
  `python3 scripts/sync.py $ARGUMENTS`.
- If `python3` or `git` is missing, or the script is genuinely not found at either
  path, report that plainly and stop — don't hand-roll the sync as a substitute.

## 3. Interpret the exit code — a non-zero exit is NOT always failure
- **Exit 0** — synced cleanly (or already up to date). Report the summary.
- **Exit 1** — synced **with conflicts**. This is the *expected* outcome when local
  edits collide with upstream; it is not a script failure. The lock was still
  written and the merged files are on disk. Tell the user to resolve them:
  - open each file containing `<<<<<<<` / `=======` / `>>>>>>>` markers, pick the
    right side, and remove the markers;
  - apply each `*.rej` file's hunks to its target, then delete the `.rej`.
  Sanity-check with `grep -rl '^<<<<<<< ' . --exclude-dir=.git` (should be empty)
  and `find . -name '*.rej' -not -path './.git/*'` (should be empty).
- **Exit 2** — could not sync (dirty working tree, invalid `.rhiza/template.yml`,
  or a git failure). Relay the error message; nothing was applied. If the tree is
  dirty, tell the user to commit or stash first.

## 4. Relay the results
- Show the script's output as-is (it logs progress and a final summary to stderr).
- After a clean sync, review the changed files with `git status` / `git diff` and
  commit them; this command does not commit for you.
- For the sync metadata this writes, see `/status`; for the managed file list, `/tree`.
