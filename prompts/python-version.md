# Python version (internal procedure)

> **Not a slash command.** This file lives in `prompts/`, not `commands/`, so the
> user cannot invoke it. `prompts/skeleton.md` reads it and follows it at its
> step 5, which is itself reached from `/rhiza:init`.

**This is a thin wrapper around the bundled `scripts/set_python_version.py`.**
The `pyproject.toml` editing — pinning `requires-python` and rewriting the Python
version classifiers to the supported range while preserving other classifiers —
lives in that deterministic, stdlib-only script. **The supported floor is Python
3.11; 3.9 and 3.10 are not supported.**

`requires-python` is the **upstream** fact here: `.python-version` is pinned from it
(step 3) and `ruff` derives its `target-version` from it (step 4). Set it first and
the rest follows.

## 1. Settle the target version
- If the caller passed a version (e.g. `$PYTHON_VERSION` from the skeleton step), use
  it (hold as `PYTHON_VERSION`).
- Otherwise ask with `AskUserQuestion`, offering **3.11**, **3.12**, **3.13**, and
  **3.14** only. Do **not** offer 3.9 or 3.10 — they're unsupported, and the script
  rejects them.

## 2. Retarget pyproject.toml
Invoke the bundled script with the plugin-root path (`${CLAUDE_PLUGIN_ROOT}`
resolves at runtime — **keep the quotes**; in a source checkout it's empty, so fall
back to the repo-relative `scripts/set_python_version.py`):
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/set_python_version.py" . \
  --python-version "$PYTHON_VERSION"
```
This sets `requires-python = ">=$PYTHON_VERSION"` and rewrites the
`Programming Language :: Python :: X.Y` classifiers to `$PYTHON_VERSION` and up,
scrubbing any stale/unsupported ones (including a bare `:: 3`).

## 3. Sync the `.python-version` pin — with `uv`, not by hand
The script edits `pyproject.toml` only. Bring the dev pin into step using the tool
that owns that file:
```bash
uv python pin --no-python-downloads "$PYTHON_VERSION"
```
Run it **after** step 2, and **keep `--no-python-downloads`**, for two reasons worth
knowing:
- without it, `uv python pin` *downloads* the interpreter if it isn't installed (~25
  MiB, unprompted) — a metadata step should not fetch a toolchain;
- with it, `uv` refuses a pin that contradicts the `requires-python` step 2 just
  wrote, which is a free consistency check. If it errors that way, **stop and
  report** — the two files disagree and something upstream is wrong.

Don't `Write` the file yourself. If `uv python pin` is unavailable for any reason,
writing `$PYTHON_VERSION` as a single line is an acceptable fallback — say that you
fell back.

Note `uv` will *warn but still succeed* on a nonsense version, so it is not the
validation layer; step 1 and the script are (both reject anything outside 3.11–3.14).

## 4. Check ruff's `target-version` — report, don't fix
`ruff` normally **infers** its `target-version` from `requires-python`, so step 2 is
usually all that's needed. But rhiza's synced `ruff.toml` currently hardcodes
`target-version = "py311"`, which *overrides* that inference — leaving a repo on
3.13 with `requires-python = ">=3.13"` while ruff still lints as py311.

- `grep -n 'target-version' ruff.toml pyproject.toml` (whichever exists).
- If a hardcoded `target-version` disagrees with `$PYTHON_VERSION`, **report the
  mismatch** and say the fix belongs upstream in the template.
- **Do not edit `ruff.toml`.** It is template-owned: a local edit is reverted by the
  next `/update` sync and flagged as non-template by `stage_synced.py`. Removing the
  line so ruff can infer is an upstream change to `jebel-quant/rhiza`.

## 5. Report
Relay the script's `modified`/`notes` output (which `pyproject.toml` fields changed,
or "already up to date"), whether `.python-version` was re-pinned, and any
`target-version` mismatch from step 4. Remind the user that CI matrices and other
version references elsewhere are out of scope — check them separately if the change
drops or adds a version.
