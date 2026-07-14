---
description: Scaffold a new source module and its mirrored test file in a rhiza-managed Python repo — creates src/<pkg>/<name>.py (with a docstring, and optional --class stubs) plus the matching tests/<pkg>/test_<name>.py, keeping the 1:1 test/source layout parity that check_test_layout.py enforces. Runs the bundled scripts/new_module.py (stdlib-only). Creates only what's missing; never overwrites.
argument-hint: "<module name>  (e.g. parsing or utils.parsing); optional --class Name"
allowed-tools: Bash(python3*), Read
---

You are running `/new` in the **current working directory's repo**.

**This command is a thin wrapper around the bundled `scripts/new_module.py`.** All
the path mirroring and stub rendering live in that script — a deterministic,
stdlib-only Python program. It creates a source module and the matching test file
so the pair satisfies `scripts/check_test_layout.py` (the same 1:1 parity gate
`/quality` runs): the test mirrors the module's path relative to `src/`, and every
`class Foo` gets a `TestFoo`. Do **not** hand-write these files yourself — run the
script so the layout stays correct by construction.

Argument: `$ARGUMENTS` — the module name, optionally dotted or slashed for a
subpackage (`parsing`, `utils.parsing`, `utils/parsing`).

## 1. Run the script
Invoke it with the plugin-root path (it ships inside this plugin, so
`${CLAUDE_PLUGIN_ROOT}` resolves at runtime — **keep the quotes**):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/new_module.py" $ARGUMENTS
```

- Pass the module name through as the first positional argument.
- Flags, added only when the user asks:
  - `--class <Name>` — also scaffold `class Name` in the module and a matching
    `TestName` in the test file. Repeatable for several classes. A module with no
    `--class` gets one docstringed placeholder function instead (so it isn't empty).
  - `--src <dir>` / `--tests <dir>` — override the source/tests roots (defaults
    `src` / `tests`). Pass these to match the repo if `/quality`'s layout check is
    configured with non-default roots.
  - a trailing repo-root path — defaults to the current directory.
  - `--json` — emit a `{created, skipped}` report instead of human-readable lines.

## 2. If the script can't run
- If `${CLAUDE_PLUGIN_ROOT}` is empty (e.g. you're in a source checkout of this repo,
  not an installed plugin), fall back to the repo-relative path:
  `python3 scripts/new_module.py $ARGUMENTS`.
- If `python3` is missing, or the script is genuinely not found at either path,
  report that plainly and stop — don't hand-roll the scaffold as a substitute.
- The script exits **1 on a usage error** (no package under `src/`, more than one
  package without an explicit `--src`, or an invalid module/class name) and prints
  the reason to stderr. Relay it; don't try to work around it by writing files
  directly.

## 3. Relay the results
- Show the script's `created` / `skipped` lines as-is. Existing files are never
  overwritten — a re-run just reports them as skipped.
- The stubs are intentionally minimal (a docstring plus `TODO`s). Point the user at
  the created files to flesh out, and remind them the new test starts as a
  placeholder — replace the `TODO` with a real assertion before `/quality`.
