# `/rhiza:completions`

Install shell tab-completion for make targets, so `make <TAB>` lists the targets of
whatever project your shell is sitting in.

```text
/rhiza:completions [bash, zsh or both]
```

With no argument it installs both, because nothing can reliably detect the shell you log
in with and an unused completion file is inert.

## This is the one command that writes outside a repo

Every other command here edits the working tree, and a PR or a `git checkout` is the
undo. This one writes into your home directory:

| Shell | Bundled script | Destination |
| --- | --- | --- |
| bash | `plugin/scripts/completions/rhiza-completion.bash` | `${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions/make` |
| zsh | `plugin/scripts/completions/rhiza-completion.zsh` | `${XDG_DATA_HOME:-$HOME/.local/share}/zsh/site-functions/_make` |

That is why it is **not model-invocable** — like [`/rhiza:detach`](detach.md) and
[`/rhiza:release`](release.md), you have to name it. Claude will not reach for it off a
description match.

**Install it once per machine.** The completion is generic: it discovers targets by
parsing the make database in the current directory, so it works in every make project you
have, rhiza-managed or not. Running it again in a second repo just reports `already up to
date`.

## Why the plugin owns this, and the template used to

The rhiza template shipped these two scripts into every managed repo, under
`.rhiza/completions/`, with a `make install-completions` target that copied them to the
paths above. Four files per repo — 75 + 116 lines of script, a 277-line README and a
42-line makefile fragment — none of which varied per repository, all of them installing to
one *machine-wide* location. N synced repos each carried an identical copy of a script
whose destination they shared, and the last copy to run won.

A developer-machine concern was being driven by repo content. The plugin is installed once
per machine, so this is where it belongs; the template drops
`.rhiza/completions/` and `completions.mk` from its `core` bundle once this has shipped
(see [issue #192](https://github.com/jebel-quant/rhiza-claude/issues/192)). If your repo
still has `make install-completions`, either route works today and both write the same
bytes to the same place.

## The follow-up step

Copying the file is not the whole job, and this is the half that gets skipped:

- **bash** — start a new shell, or `source` the installed file. `bash-completion` itself
  has to be installed and enabled for that directory to be read at all.
- **zsh** — the destination must be on `fpath` *before* `compinit` runs:

  ```zsh
  fpath=(${XDG_DATA_HOME:-$HOME/.local/share}/zsh/site-functions $fpath)
  autoload -U compinit && compinit
  ```

The command prints the relevant line for whichever shells it installed.

## When it refuses

The installed filenames are `make` and `_make` — the generic names both shells resolve for
the `make` command. Anything else would be politer and would never fire for a bare
`make <TAB>`, which is the entire point. It also means the destination is exactly where a
make completion from Homebrew, a distro package or your own dotfiles would sit.

So a destination that holds a file **this plugin did not write** is left alone, reported,
and the command exits 3. Nothing is overwritten silently. Your options are to re-run with
`--force`, or to wire the bundled script up by hand from somewhere else (below). Claude
will ask rather than forcing on its own.

Re-running over the plugin's *own* earlier copy is not that case: an older copy is
recognised by its `_rhiza_make` function prefix and updated in place.

## Manual setup

Nothing in either script depends on where it lives, so any of these work instead of the
command. Substitute the plugin's install path — `/rhiza:completions --dry-run` prints the
source path for each shell.

Source it from `~/.bashrc`:

```bash
source /path/to/rhiza/scripts/completions/rhiza-completion.bash
```

Put it on `fpath` as `_make` for zsh:

```zsh
mkdir -p ~/.zsh/completion
cp /path/to/rhiza/scripts/completions/rhiza-completion.zsh ~/.zsh/completion/_make
# then, in ~/.zshrc:
fpath=(~/.zsh/completion $fpath)
autoload -U compinit && compinit
```

Or install system-wide, for every user on the machine:

```bash
sudo cp /path/to/rhiza/scripts/completions/rhiza-completion.bash /etc/bash_completion.d/rhiza
sudo cp /path/to/rhiza/scripts/completions/rhiza-completion.zsh /usr/local/share/zsh/site-functions/_make
```

## What completes

Targets, from the `Makefile` and every `.mk` file it includes:

```console
$ make te<TAB>
test
```

Common overridable variables — `DRY_RUN=1`, `ENV=dev|staging|prod`, and (zsh only)
`COVERAGE_FAIL_UNDER=`, `PYTHON_VERSION=`:

```console
$ make ENV=<TAB>
dev  staging  prod
```

Under zsh you also get each target's `##` description, which is the same text
`make help` prints:

```console
$ make <TAB>
book     -- build the docs site into _book/
lint     -- all prek hooks over every file
test     -- pytest over tests/, 100% coverage gate
```

## Aliases

If you type `m` rather than `make`, register the same function for it in your shell
config:

```bash
alias m='make'
complete -F _rhiza_make_completion m   # bash
```

```zsh
alias m='make'
compdef _rhiza_make m                  # zsh
```

## How it works

1. **Target discovery** — parse the full make database (`make -qp`) in the current
   directory. Nothing is read from `.rhiza/`, so an unmanaged project completes too.
2. **Descriptions** — the `##` comment after a target name, under zsh.
3. **Caching** — the target list is written to
   `${XDG_CACHE_HOME:-$HOME/.cache}/rhiza/`, keyed per directory, because parsing the
   database is slow on a large `Makefile`.
4. **Invalidation** — the cache is stale as soon as `Makefile`, `local.mk`,
   `.rhiza/rhiza.mk` or any `.rhiza/make.d/*.mk` is newer than it, so only the first Tab
   after a makefile change pays the parse. Those last two are the retired make layer,
   kept because a repo pinned to a pre-v1.4 template still has them; on a current
   template — and outside a rhiza repo entirely — they match nothing.

Force a refresh by deleting the cache:

```bash
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/rhiza"
```

If the cache directory cannot be created — a read-only home, say — completion falls back
to parsing on every Tab press rather than failing.

## Troubleshooting

**No completion at all, bash.** Check that `bash-completion` is installed
(`apt-get install bash-completion`, `brew install bash-completion@2`) and sourced from
your `~/.bashrc`; the user completion directory is only read when it is.

**No completion at all, zsh.** Check `compinit` is called in `~/.zshrc`, that the
destination is in `$fpath`, and clear a stale cache with `rm -f ~/.zcompdump` before
re-running `compinit`.

**Completion loads, no targets appear.** You are probably not in a directory with a
`Makefile` — both scripts return immediately when there isn't one. Otherwise check that
`make -qp` parses the project's makefiles at all; the completion sees exactly what it
prints.

**A different make completion wins.** Some other file earlier on `fpath`, or a
`complete -F` registered after ours, is taking precedence. `complete -p make` (bash) or
`which _make` (zsh) says which one is live.

## Notes

- **Needs no repo, no git and no network.** Like [`/rhiza:maffay`](maffay.md), it runs
  anywhere — including outside a rhiza-managed project, which is most of the point.
- The installer is `plugin/scripts/install_completions.py`, stdlib-only, so `uv` is the
  only requirement. `--dry-run` reports the destinations and the verdict per shell
  without writing; `--json` returns the same summary as one object.
- Uninstalling is `rm` on the two paths in the table above. Nothing else is touched, and
  no state is kept anywhere else.

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/skills/completions/SKILL.md` |
| **Invocation** | `/rhiza:completions [bash, zsh or both]  (optional; defaults to both)` |
| **Model-invocable** | no — excluded from model invocation |
| **Allowed tools** | `Bash(uv*)` |

<!-- generated:end -->
