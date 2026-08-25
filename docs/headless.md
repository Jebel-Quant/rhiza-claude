# Without Claude Code

Some people want rhiza's template sync without an LLM anywhere near it — in CI, in a
`Makefile`, from a shell script, or just because they'd rather drive it themselves. That
works, and it needs nothing this repository doesn't already ship.

The reason is the plugin's central split: **deterministic work belongs in tested code,
judgement belongs in markdown.** Everything with one right answer — parsing the lock,
cloning a pinned ref, merging synced files, staging exactly what was delivered — is
Python under `plugin/scripts/`, stdlib-only, type-checked and covered. The markdown
around it supplies the judgement. Take the markdown away and the scripts still run.

!!! note "This is the same code path, not a second one"
    Nothing here is a re-implementation. `/rhiza:update` shells out to the very
    `sync.py` invocation shown below; the command's contribution is resolving which ref
    to move to, reading the exit code, and writing a PR body. A separate CLI would be a
    second implementation of sync to keep in step with the first, and that is the one
    thing this project has decided not to maintain. One operation, one entry point.

## Setup

```bash
git clone https://github.com/Jebel-Quant/rhiza-claude.git ~/.local/share/rhiza-claude
export RHIZA=~/.local/share/rhiza-claude/plugin/scripts
```

That is the whole install. No `/plugin install`, no `rhiza` package on PyPI, no
dependencies — the scripts import nothing outside the standard library, and each puts
its own directory on `sys.path`, so running one by absolute path works from any
directory.

**Use Python 3.12.** `tomllib` and `datetime.UTC` put the hard floor at 3.11, but 3.12
is the version every command pins and the only one CI exercises. A bare `python3` on
macOS is 3.9 and crashes `sync.py`. The commands get 3.12 through `uv`, and so should
you:

```bash
py() { uv run --python 3.12 --no-project python "$@"; }
py "$RHIZA/status.py" .
```

`--no-project` stops `uv` resolving the *target* repo's environment for a script that
needs no environment at all. Every example below assumes those two definitions.

Most scripts take `--json`, which is the surface to script against: human output is
prose and may be reworded, the JSON keys are what the tests pin.

## What maps, and what doesn't

<!-- rhiza-count: commands -->
Six of the ten slash commands are deterministic end to end and have an exact headless
equivalent. The other four exist *because* they need a reading of your repository that
no script can perform.

| Command | Headless equivalent | What you give up |
| --- | --- | --- |
| [`/rhiza:status`](skills/status.md) | `status.py`, `validate.py` | nothing |
| [`/rhiza:update`](skills/update.md) | `sync.py` → `resolve_conflicts.py` → `stage_synced.py` | ref resolution and the PR body |
| [`/rhiza:init`](skills/init.md) | `init_scaffold.py`, `init_skeleton.py`, `set_license.py` | the interview that fills in the flags |
| [`/rhiza:detach`](skills/detach.md) | `detach.py` | nothing |
| [`/rhiza:completions`](skills/completions.md) | `install_completions.py` | nothing |
| [`/rhiza:maffay`](skills/maffay.md) | `maffay.py` | nothing |
| [`/rhiza:quality`](skills/quality.md) | `check_make_targets.py` probes the gates | **the score** — reading a repo and judging it is the command |
| [`/rhiza:docs`](skills/docs.md) | `render_badges.py`, `sync_readme_help.py` | the prose, which is most of it |
| [`/rhiza:release`](skills/release.md) | `check_version_bump.py`, `bump-my-version`, `git-cliff` | choosing the version, writing the changelog section |
| [`/rhiza:remote`](skills/remote.md) | `pr_status.py` reports what CI said | diagnosing the failure and fixing it |

The bottom four are worth being precise about. They are not commands that were never
scripted; they are commands whose deterministic half **was already** extracted into the
scripts named beside them. What is left over in each is irreducibly a judgement:
whether a finding matters, whether a breaking change should spend the 1.0 signal, what
to preserve in a README someone wrote by hand.

## Read-only: what state is this repo in?

```bash
py "$RHIZA/validate.py" .              # is .rhiza/template.yml well-formed?
py "$RHIZA/status.py" . --files        # what did the last sync actually deliver?
py "$RHIZA/status.py" . --check        # is the pinned ref behind the latest release?
```

`validate.py` exits 0 when the configuration passes and 1 when it fails, which makes it
usable as a CI gate as-is. `status.py --json` gives you the lock's contents — repo, ref,
commit SHA, timestamp, strategy, file list — as one object.

## The sync, step by step

This is `/rhiza:update` with the judgement taken out. Do it on a branch; the sync
refuses a dirty tree.

**1. Pick the ref and bump the pointer.** The command asks the forge for the template's
latest release and refuses a major bump without confirmation. Headless, you name it:

```bash
TARGET=v1.5.2
git checkout -b "rhiza_$TARGET" origin/main
sed -i.bak "s/^ref: .*/ref: \"$TARGET\"/" .rhiza/template.yml && rm .rhiza/template.yml.bak
git commit -am "chore: bump rhiza to $TARGET"
```

Change `ref:` and nothing else. `profiles:`, `templates:`, `exclude:` and `language:`
are a deliberate, separate decision — a version bump should not carry one.

**2. Sync.** Read the exit code before doing anything else; all three are expected:

```bash
py "$RHIZA/sync.py" .
```

| Exit | Meaning |
| --- | --- |
| 0 | synced cleanly, or already up to date |
| 1 | synced **with conflicts** — the lock is written and merged files are on disk |
| 2 | could not sync (dirty tree, invalid `template.yml`, git failure) — nothing applied |

**3. Resolve conflicts, on exit 1 only.** Take the upstream side of every marker — a
rhiza-managed file is the template's to own, so local divergence in one is drift to
undo, not work to preserve:

```bash
py "$RHIZA/resolve_conflicts.py" .
```

Exit 0 means every marker is resolved. Exit 1 means a `*.rej` file remains and needs a
human — the sync cannot create those, so one here predates this run. Exit 2 means a
malformed conflict block and **nothing was written**.

**4. Stage only what the template owns.** Never `git add --all` here. The lock records
exactly which paths the sync materialized, and this stages precisely that set,
deletions included, printing anything it deliberately left behind:

```bash
py "$RHIZA/stage_synced.py" . --json
SKIP=check-managed-files git commit -m "chore: apply rhiza sync $TARGET"
```

Exit 1 means there is no lock — the sync never ran. Exit 2 is a git failure. Exit 3
means the lock names a path resolving outside the repository and nothing was staged;
report it rather than hand-staging around it.

Keep the `SKIP=`. rhiza-hooks' `check-managed-files` refuses a commit touching any path
in the lock's `files:` list, and this commit is by construction exactly that list.

**5. Open the request**, if you want the same PR the command would open:

```bash
py "$RHIZA/platform_cli.py" pr-create --base main --head "rhiza_$TARGET" \
    --title "chore: update rhiza to $TARGET" --body-file BODY.md
```

It reads `origin` and issues `gh pr create` or `glab mr create`, which differ in
subcommand *and* flag names. Or push the branch and open it yourself — nothing
downstream depends on how the request was created.

## Becoming rhiza-managed

`/rhiza:init` detects the platform, owner and name from `origin` and asks when it can't.
Headless, you pass what it would have detected:

```bash
py "$RHIZA/init_scaffold.py" . --host github --language python --ref v1.5.2
py "$RHIZA/init_skeleton.py" . --owner my-org --repo my-lib --language python \
    --description "..."
py "$RHIZA/set_license.py" . --license MIT --owner "My Org"
```

`init_scaffold.py` writes `.rhiza/template.yml` and **syncs nothing** — the template
content arrives with the first `sync.py`, exactly as it does with the command. Check
that the ref you pin actually defines the profile before you rely on it:

```bash
py "$RHIZA/check_template_profile.py" github-project \
    --template-repo jebel-quant/rhiza --ref v1.5.2
```

A ref that doesn't define the profile fails here rather than at the first sync.

## Leaving

```bash
py "$RHIZA/detach.py" . --force
```

Deletes every file `.rhiza/template.lock` records, prunes the emptied directories and
removes the lock. `--force` skips the confirmation prompt; without a TTY the prompt is
treated as "no" and the run cancels, so `--force` is required from a script.

## Machine setup

```bash
py "$RHIZA/install_completions.py" --shell both
```

Generic `make` tab-completion, installed under `${XDG_DATA_HOME:-$HOME/.local/share}`.
It refuses to overwrite a completion it did not write unless `--force` is passed. Not
repo-specific, so it works in every project on the machine.

## What this page is not needed for

Day-to-day work in a rhiza-managed repository already involves no LLM and no plugin.
The gates arrive as a task runner and a `Makefile` shim, and `make fmt`, `make test` and
`make lint` are what you run. The plugin only appears at the lifecycle moments — adopt,
sync, score, release — which is why the headless surface above is small.

!!! warning "The commands are the contract, the flags are the implementation"
    CI gates every flag a command passes, so a renamed flag fails the build rather than
    a user's task. That check spans the commands only. If you script against these
    invocations directly, pin the clone to a release tag and read the changelog before
    moving it — you are using the engine, not a published CLI, and it is versioned as
    part of the plugin rather than on its own.
