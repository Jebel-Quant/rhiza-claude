# Install uv (internal procedure)

> **Not a slash command.** This file lives in `prompts/`, not `commands/`, so the
> user cannot invoke it. `/rhiza:init` and `/rhiza:update` read it and follow it as
> their **first** step.

Goal: **`uv --version` works when this procedure finishes**, or the user knows
exactly why it doesn't.

Every rhiza command runs the bundled scripts through
`uv run --python 3.12 --no-project python …`, so `uv` is the plugin's one hard
dependency. This procedure exists so the commands don't each carry their own install
prompt — they read this one at their first step.

**Never install without asking.** Installing a toolchain touches the user's machine
outside this repo, so `AskUserQuestion` first. If they decline, stop and point them
at <https://docs.astral.sh/uv/getting-started/installation/> — don't improvise
another route.

## 1. Is it already there?

Run `uv --version`. If it succeeds, you're done: **say so in one line** and return to
the calling command — don't report a version banner or narrate a no-op, since this is
the common case on every `/init` and `/update` run. Do **not** upgrade a working
`uv`; that's the user's call, not this procedure's.

## 2. Pick the installer

`uv` is missing. Detect the platform (`uname -s`: `Darwin`/`Linux`; otherwise assume
Windows) and ask the user (`AskUserQuestion`) how to install it:

- **macOS / Linux** — offer, in this order:
  1. **Official installer (Recommended)** — `curl -LsSf https://astral.sh/uv/install.sh | sh`.
     Works everywhere, installs to `~/.local/bin`, needs no admin rights.
  2. **Homebrew** — `brew install uv` (macOS, or Linuxbrew). Only offer this when
     `brew` is actually on `PATH`; it puts `uv` under the brew prefix and upgrades
     with `brew upgrade`.
  3. **Don't install** — stop and link the docs.
- **Windows** — offer `winget install --id=astral-sh.uv -e`, the PowerShell
  one-liner from the installation docs, or "don't install".

Both macOS/Linux options fetch and execute a vendor script or formula — say so
plainly in the question so the user is choosing knowingly.

## 3. Install

Run only the command the user chose, exactly as written above. Relay its output. If
it fails, report the actual error and stop — don't silently fall back to the other
method; the user picked one, and a failure usually means something worth reading
(no network, a proxy, a locked-down `PATH`).

## 4. Verify, and sort out `PATH`

Re-run `uv --version`.

- **It works** → report the version and path.
- **It fails but `uv` was installed** — the standard case for the official
  installer, which drops the binary in `~/.local/bin` without touching the current
  shell's `PATH`. Check `~/.local/bin/uv --version` (or the brew prefix). If the
  binary is there, say so and tell the user the install succeeded but **this shell
  needs a new `PATH`**: they should open a new terminal, or run
  `source $HOME/.local/bin/env` (the installer writes it), or add
  `export PATH="$HOME/.local/bin:$PATH"` to their shell profile. Do **not** edit
  their shell profile yourself.
- **No binary anywhere** → report that the install did not take effect and link the
  installation docs.

## 5. Return to the caller

This is a precondition step, not a destination — keep the output proportionate:
- **`uv` was already there** — one line, then continue with the calling command.
- **`uv` was just installed** — say what was installed and where, plus any `PATH`
  step the user still needs to take, then continue.
- **`uv` still doesn't work** — say so and **stop the calling command too**. Nothing
  downstream in `/init` or `/update` can run: both drive the bundled scripts through
  `uv run`, and `/update`'s sync and gates are entirely `uv`-dependent. Do not
  attempt a fallback to a system `python3` — macOS ships 3.9, where `sync.py` crashes
  on `datetime.UTC`.
