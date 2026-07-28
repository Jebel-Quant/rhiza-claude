# pr-base (internal)

Get a work branch based on an up-to-date remote default branch — **without ever
pushing to that default branch**.

!!! note "Not a slash command"
    This is an **internal procedure** (`prompts/pr-base.md`), not something you
    invoke. Both [`/rhiza:init`](../commands/init.md) and
    [`/rhiza:update`](../commands/update.md) read and follow it, which is why they
    behave identically here.

## The rule it exists to enforce

**The default branch is never pushed to** — not for a seed commit, not to bring it
into being on a brand-new repo. A protected default must stay untouched, and a repo's
first commit belongs to its owner. So when `origin/<default>` doesn't exist yet, the
procedure **asks you** to create the repository initialised with an empty README, and
stops the calling command if you don't. It will not push one itself.

## What it does

1. **Determines the default branch** — `gh repo view --json defaultBranchRef` or
   `git remote show origin`, falling back to `main`.
2. **Makes `origin/<default>` resolve** — a plain `git fetch` when it already exists;
   otherwise it asks you to create the repo with `--add-readme` (or the GitLab
   equivalent), wires up the remote, fetches, and re-reads the default. If it still
   doesn't resolve, the calling command **stops**.
3. **Creates the work branch** off `origin/<default>` — `rhiza_init_<date>` for
   `/init`, `rhiza_<target>` for `/update`, with a time suffix if the name is taken.
   Uncommitted work that predates the command is left strictly alone: never stashed,
   never discarded.
