# With another agent

The plugin is written for Claude Code, but very little of it is *about* Claude Code. The
deterministic half — the sync, the lock parsing, the merge, the staging — is stdlib-only
Python with its own CLI, and [Without Claude Code](headless.md) drives it with no model
in the loop at all. What is left is the prose: ten commands and nine procedures, in the
`SKILL.md` format that many clients now read.

So the gap is small and specific, and `bundle/` closes it.

## Use it

```bash
git clone https://github.com/Jebel-Quant/rhiza-claude.git ~/.local/share/rhiza-claude
export RHIZA_ROOT=~/.local/share/rhiza-claude
```

Then point your client at `$RHIZA_ROOT/bundle/skills` — copy or symlink those
directories into wherever it loads skills from. Each is named `rhiza-<command>`, because
a skills folder is a shared namespace and `docs`, `status` and `release` are names
somebody else will want too.

`uv` and `git` on PATH is the whole dependency list; there is no package to install.

!!! warning "`bundle/prompts/` are not skills"
    They are procedures a skill reaches with a file read, and several are shared between
    commands. A client that loaded them as skills would offer the user half a workflow —
    which is the same reason they sit outside every discovery location in the plugin.

## What the translation changes

Nothing in the prose. Five bindings are rewritten or restated, and they are the whole
list:

| Binding | In the bundle |
| --- | --- |
| `${CLAUDE_PLUGIN_ROOT}` | `${RHIZA_ROOT}`, pointing at your checkout — the scripts are **not** copied, so a bundled skill runs the same file the plugin runs |
| `$ARGUMENTS` | still written, with a preamble note to substitute it where the client doesn't |
| `/rhiza:<name>` | still written, with a note that it means the `rhiza-<name>` skill beside it |
| `allowed-tools` | dropped from the frontmatter, restated in prose as the binaries the skill runs |
| `argument-hint`, `disable-model-invocation` | dropped, restated the same way |

The frontmatter is reduced to `name` and `description` — the two fields the open format
requires. `name` is the interesting one: a *plugin* skill must not carry it, because
there the directory decides the command, and the open format requires it. The two
spellings contradict each other, which is why the bundle is generated rather than
maintained by hand.

## What you give up

- **The `PreToolUse` guard.** In Claude Code a hook makes three rules structural: one
  bare `make` per gate, never force-push, never push to the default branch. Elsewhere
  they are prose promised by the commands that make them. If your client has hooks,
  `plugin/scripts/hook_bash_guard.py` is worth wiring into them; if it doesn't, the
  rules rest on the model honouring them.
- **The tool allow-list.** `allowed-tools` is enforcement in Claude Code and a comment
  anywhere else, so each bundled skill states in prose what it runs instead. That is a
  fact a model can act on, not a permission a client silently didn't apply.
- **`AskUserQuestion`.** Where a command asks the user to choose — which findings to
  file, which version to release — a client without a question tool should ask in plain
  text, number the options, and wait. Every "nothing happens without an explicit
  selection" rule in the prose holds however the question was put.

!!! note "Tested here, verified there"
    CI gates that the bundle is **current** and that its translation is complete — no
    surviving `${CLAUDE_PLUGIN_ROOT}`, a skill per command, no orphan left by a rename.
    What it cannot test is another client's behaviour: no runner here loads Cursor,
    Codex or Gemini CLI. So "the bundle is correct" is a checked claim, and "the command
    behaves the same there" is one you should confirm on the first run.

## Keeping it current

`bundle/` is generated and **committed**, so that pointing a client at a checkout needs
no build step. Regenerate it whenever a command or procedure changes:

```bash
make bundle
```

A stale bundle fails the build: `plugin/scripts/build_bundle.py --check` runs as a
`prek` hook over the sources and the bundle alike, the same arrangement the docs
reference blocks use. Never edit a file under `bundle/` — the next generation
overwrites it.
