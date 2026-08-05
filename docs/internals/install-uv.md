# install-uv (internal)

Make sure [`uv`](https://docs.astral.sh/uv/) is available on this machine,
installing it if it isn't.

!!! note "Not a slash command"
    This is an **internal procedure** (`plugin/prompts/install-uv.md`), not something you
    invoke. Both [`/rhiza:init`](../skills/init.md) and
    [`/rhiza:update`](../skills/update.md) follow it as their **first** step, so
    `uv` gets installed as part of using them — there's nothing to run yourself.

Every rhiza command runs its bundled scripts through
`uv run --python 3.12 --no-project python …`, so `uv` is the plugin's one hard
dependency. This procedure exists so the commands don't each carry their own install
prompt.

## What it does

1. **Checks for an existing `uv`** (`uv --version`). If it's there, it reports the
   version and path and **stops** — nothing is installed, nothing is changed, and a
   working `uv` is never upgraded behind your back.
2. **Asks how to install it** — it never installs without your approval:
   - **macOS / Linux** — the official installer
     (`curl -LsSf https://astral.sh/uv/install.sh | sh`, recommended: no admin
     rights, installs to `~/.local/bin`), or `brew install uv` when Homebrew is on
     your `PATH`.
   - **Windows** — `winget install --id=astral-sh.uv -e`, or the PowerShell
     one-liner from the installation docs.

   Declining stops the calling command with a link to the
   [installation docs](https://docs.astral.sh/uv/getting-started/installation/).
3. **Runs the chosen installer** and relays its output. A failure is reported as-is
   — it does not silently retry the other method.
4. **Verifies and sorts out `PATH`** — re-runs `uv --version`. If the binary landed
   in `~/.local/bin` but the current shell can't see it yet (the usual outcome of the
   official installer), it says so and tells you how to fix *your* shell — open a new
   terminal, `source $HOME/.local/bin/env`, or add the directory to your profile. It
   does **not** edit your shell profile for you.

## Notes

- Read-only when `uv` is already installed.
- It installs `uv` itself, nothing else — no Python toolchains, no project
  environments. Those come from the commands that use `uv`.

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/prompts/install-uv.md` |
| **Invocation** | **not a slash command** — reached with `Read`, never invoked |
| **Read by** | [`/rhiza:init`](../skills/init.md), [`/rhiza:update`](../skills/update.md), [`skeleton`](skeleton.md) |

<!-- generated:end -->
