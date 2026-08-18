---
description: Install shell tab-completion for make targets, so `make <TAB>` lists a project's targets. Writes to the user's data directory, not to the repo. Works in any make project.
argument-hint: "[bash, zsh or both]  (optional; defaults to both)"
allowed-tools: Bash(uv*)
disable-model-invocation: true
---

You are running `/completions`. Goal: install the bundled make tab-completion for the
user's shell, so `make <TAB>` lists the targets of whatever project their shell is
sitting in.

**Two things make this command unlike every other one here.** Read both before you run
anything.

1. **It writes outside the repo.** The destinations are under
   `${XDG_DATA_HOME:-$HOME/.local/share}` — the user's home, not the working tree. There
   is nothing to review in a PR afterwards and nothing a `git checkout` undoes. That is
   why the user has to name this command: it is not model-invocable.
2. **It is not repo-scoped at all.** The completion is generic make completion — it
   discovers targets by parsing the make database in the current directory — so it works
   in every make project on the machine, rhiza-managed or not. **Install it once per
   machine**, not once per repo. If the user asks you to run it "for this repo", say that
   and install it once anyway; a second run is a no-op that reports `already up to date`.

This replaces the `make install-completions` target the rhiza template used to sync into
every managed repo, where N repos each carried an identical copy of a script that
installs to one shared path. If the user's repo still has that target, either one works
today and they do the same thing — prefer this one, and say why.

Argument (optional): `$ARGUMENTS` — `bash`, `zsh` or `both`. Default `both`.

## 1. Work out which shell

**Do not guess from `$SHELL` and install only that one.** Installing an unused
completion file is inert; installing the wrong single one leaves the user with no
completion and no error. So:

- `$ARGUMENTS` names a shell → pass it through.
- `$ARGUMENTS` is empty → `both`, and say so in the report.

`fish` and anything else is unsupported. The script rejects it with argparse's own
message; relay that rather than improvising a fish completion.

## 2. Install

`${CLAUDE_PLUGIN_ROOT}` resolves at runtime (**keep the quotes**); in a source
checkout it's empty, so fall back to the repo-relative path
`plugin/scripts/install_completions.py`.

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/install_completions.py" --shell both
```

Swap `both` for the shell from step 1. Two flags exist for the cases below and
should not be passed speculatively:

- `--dry-run` — print the destinations and the verdict per shell, write nothing. Use it
  when the user asks *where* this would install, or wants to see the plan first.
- `--force` — replace a completion at the destination that this plugin did not write.
  **Never pass it on the first run.** See step 3.

`--json` gives the same summary as one object if you need to read a field rather than
show a line.

## 3. Handle the one blocking case

Exit **3** means a destination already holds a completion **this plugin did not write** —
the filenames are `make` and `_make`, the generic names both shells resolve for the
`make` command, so a completion from Homebrew, a distro package or the user's own dotfiles
lands in exactly that spot. The script has changed nothing and named the path.

**Stop and ask.** Show the path and offer the two ways forward:

- re-run with `--force`, which overwrites that file with ours; or
- leave it alone and wire ours up by hand from
  `"${CLAUDE_PLUGIN_ROOT}/scripts/completions/"` — the docs page carries the manual
  setup, and the header comment of each script repeats it.

Do **not** re-run with `--force` on your own initiative, and do not delete the file to
make the un-forced run succeed. Overwriting a completion the user installed deliberately
is precisely the surprise the exit code exists to prevent.

## 4. Report

Relay the script's lines as printed — one per shell, each with its destination and its
follow-up step. The follow-up is the half that matters and the half users skip:

- **bash** — start a new shell, or `source` the installed file.
- **zsh** — if completion doesn't activate, the destination has to be on `fpath` before
  `compinit` runs. The line to add to `~/.zshrc` is in the output; show it verbatim.

`already up to date` means a previous run installed the same bytes. That is a success,
not a no-op to apologise for — say so in one line and stop.

Nothing here needs a repo, a git remote or a network, so there is no state to check
afterwards and nothing to commit.
