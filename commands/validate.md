---
description: Validate the repo's .rhiza/template.yml — checks it's a git repo with the expected language-specific structure, that template.yml exists and parses, and that its required/optional fields (repository, profiles/templates/include, ref, host, language, exclude) are present and well-typed. Runs the bundled scripts/validate.py (stdlib-only), so it works without the rhiza CLI installed. Exits non-zero on failure.
argument-hint: "[path to a repo root]  (optional; defaults to the current repo)"
allowed-tools: Bash(python3*), Read
---

You are running `/validate` in the **current working directory's repo**.

**This command is a thin wrapper around the bundled `scripts/validate.py`.** All the
parsing and the validation rules live in that script — a deterministic, stdlib-only
Python program that reads `.rhiza/template.yml` directly (no `rhiza` CLI, no PyYAML
required). Do **not** re-implement any check or judge the config yourself; run the
script and relay its output. Keeping the logic in one place is the point: the script
is the single source of truth.

Argument (optional): `$ARGUMENTS` — a path to the repo root to validate; default is
the current directory.

## 1. Run the script
Invoke it with the plugin-root path (it ships inside this plugin, so
`${CLAUDE_PLUGIN_ROOT}` resolves at runtime — **keep the quotes**):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate.py" $ARGUMENTS
```

- Pass `$ARGUMENTS` through as the optional target path. If it's empty, just omit it.
- Flags, added only when the user asks:
  - `--json` — emit `{valid, errors, warnings}` on stdout (progress still goes to stderr).
  - `--path-to-template <dir>` — directory holding `template.yml` (default `<TARGET>/.rhiza`; use `.` for the project root).
  - `--verbose` — also show debug-level progress lines.

## 2. If the script can't run
- If `${CLAUDE_PLUGIN_ROOT}` is empty (e.g. you're in a source checkout of this repo,
  not an installed plugin), fall back to the repo-relative path: `python3 scripts/validate.py $ARGUMENTS`.
- If `python3` is missing, or the script is genuinely not found at either path, report
  that plainly and stop — don't hand-roll the validation as a substitute.

## 3. Relay the results
- Show the script's output as-is — each check is already prefixed with ✓ / ✗ / !.
- State the verdict plainly: the script exits **0 when valid, 1 when invalid**. If it
  failed, summarize the ✗ errors that need fixing (the script already prints the fix hints).
- Warnings (`!`) don't fail validation — mention them but don't treat them as blockers.
- Don't add scores or recommendations beyond what the script emits; for a fuller
  quality assessment point the user at `/quality`.
