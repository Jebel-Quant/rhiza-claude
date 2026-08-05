# License (internal procedure)

> **Not a slash command.** This file lives in `prompts/`, which Claude Code does not
> scan for commands, so the user cannot invoke it. `/rhiza:init` reads it and follows it at its step 5c.

**This is a thin wrapper around the bundled `plugin/scripts/set_license.py`.** The metadata
edit, the bundled license texts, and the safe-overwrite logic all live in that
deterministic, stdlib-only script. The job here is to settle three inputs — the
license, the copyright holder, and whether to overwrite — then run it and relay the
result.

## 1. Settle the license id
- If the caller already knows the SPDX id (e.g. `/init` asked for it), use it (hold
  as `LICENSE`).
- Otherwise ask with `AskUserQuestion`, offering the **bundled** set — **MIT**,
  **Apache-2.0**, **BSD-3-Clause** — plus **none** (clear the metadata, leave any
  existing `LICENSE` in place). These three are the ids with full text bundled; a
  different id still sets the metadata but the script will tell you to add the
  `LICENSE` text by hand.

## 2. Settle the copyright holder
The `LICENSE` file's copyright line needs a holder (`OWNER`). Derive it without
prompting when you can, then only confirm if unsure:
- from the `origin` remote's owner — parse `git remote get-url origin`
  (`github.com/<owner>/…` or `gitlab.com/<owner>/…`); else
- from `git config user.name`; else
- ask the user (`AskUserQuestion`).

Hold as `OWNER`.

## 3. Handle an existing LICENSE (overwrite is opt-in)
If `LICENSE` **exists** and you're changing it, this is a relicense — confirm
before clobbering it:
- If the caller explicitly asked to overwrite, proceed with `--force`.
- Otherwise ask the user (`AskUserQuestion`) whether to overwrite the existing
  `LICENSE`. Only pass `--force` if they say yes. If they decline, stop this
  procedure — report that the existing `LICENSE` was kept, and let the caller
  continue.

The script itself is the backstop: without `--force` it refuses to overwrite a
differing `LICENSE` and **exits 3**, changing nothing (metadata included).

## 4. Run the script
Invoke the bundled script with the plugin-root path (`${CLAUDE_PLUGIN_ROOT}`
resolves at runtime — **keep the quotes**; in a source checkout of this repo it's
empty, so fall back to the repo-relative `plugin/scripts/set_license.py`):
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/set_license.py" . \
  --license "$LICENSE" --owner "$OWNER" [--force]
```

## 5. Report
Relay the script's `created`/`modified`/`skipped`/`notes` output: whether the
`LICENSE` file was written and whether `pyproject.toml`'s `license`/`license-files`
were set (or cleared, for `none`). If it exited 3, say the existing `LICENSE` was
left untouched and offer to re-run with `--force`.

**No `License ::` trove classifier.** The script writes the PEP 639 SPDX `license`
field and never a classifier, and neither should you — see the note at the end of
`plugin/prompts/skeleton.md` for why the template's stale assertion is not a reason to add
one.
