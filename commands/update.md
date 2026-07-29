---
description: Sync the current rhiza-managed repo to the latest (or a given) template release — bump the `ref` in .rhiza/template.yml, run the bundled stdlib-only sync, resolve any conflicts by taking the upstream side, and open a PR containing **only template-owned files** (the paths .rhiza/template.lock records, never a blanket `git add --all`). The template repository is read from template.yml, so forks and rhiza-go work too. It runs no quality gates, produces no scorecard, and files no issues — run /rhiza:quality for that. Always branches off the up-to-date default branch and restores the branch you started on.
argument-hint: "[version e.g. v1.2.0]  (optional; defaults to the template's latest release)"
allowed-tools: Bash(git*), Bash(gh*), Bash(glab*), Bash(uv*), Bash(cat*), Bash(grep*), Read, Edit, AskUserQuestion
---

You are running `/update` in the **current working directory's repo**. Goal: bump the
template `ref`, apply the sync, and open a PR with **nothing but template-owned
files** in it.

**Only files that come from the template repository may be touched.** The sync
records exactly which paths it materialized in `.rhiza/template.lock`'s `files` list,
and `scripts/stage_synced.py` (step 7) stages precisely that set — so the guarantee is
mechanical, not something this prose has to be trusted to honour. **Never
`git add --all`** and never fold in unrelated edits: no reformatting of the repo's own
source, no dependency changes, no test fixes. Anything outside the set stays in the
working tree and gets reported.

**No gates, no scorecard, no issues.** `/update` syncs; `/quality` scores. Don't run
`make test`/`make lint`/`make fmt` here — `make fmt` in particular would rewrite the
repo's own files and break the rule above. Point the user at `/rhiza:quality` in the
report instead.

Argument (optional): `$ARGUMENTS` — an explicit template version tag like `v1.2.0`.
If empty, use the template's latest release.

Work through these steps. Stop and report if a precondition fails.

## 1. Preconditions
- **`uv` first.** `Read` **`${CLAUDE_PLUGIN_ROOT}/prompts/install-uv.md`** and follow
  it before anything else (in a source checkout, `prompts/install-uv.md`). It's a
  one-line no-op when `uv` is already present. The sync runs through
  `uv run --python 3.12`, so if `uv --version` still fails afterwards, **stop** —
  don't fall back to a system `python3`, which on macOS is 3.9 and crashes `sync.py`
  on `datetime.UTC`. (`prompts/*.md` are internal procedures, not slash commands —
  outside `commands/` so the user can't invoke them; reach them with `Read`.)
- `.rhiza/template.yml` must exist. If not, stop: "Not a rhiza-managed repo (no
  .rhiza/template.yml)" — and point at `/rhiza:init`, which establishes that file.
- The working tree must be clean (`git status --porcelain`). If dirty, stop and show
  the dirty files; the sync refuses a dirty tree anyway (exit 2).
- Record `ORIG_BRANCH` (`git branch --show-current`) — step 8 returns to it — the
  default branch `DEFAULT` (`gh repo view --json defaultBranchRef --jq
  .defaultBranchRef.name`, else `git remote show origin`, else `main`), and the
  **platform** from `git remote get-url origin` (`github.com` → GitHub/`gh`; a GitLab
  host → GitLab/`glab`).

## 2. Resolve the target ref
- Read `repository` and the current `ref` (or `template-branch`, whichever key is
  present) from `.rhiza/template.yml`. Hold the repo as `TEMPLATE_REPO` — **this, not
  a hardcoded `jebel-quant/rhiza`**, is what to query. A repo may follow
  `jebel-quant/rhiza-go` or a fork, and bumping it to another project's tag would
  point the sync at a ref that doesn't exist there.
- `TARGET`:
  - `$ARGUMENTS` if non-empty, verbatim (ensure it starts with `v`);
  - else the latest release of `$TEMPLATE_REPO`:
    `gh release list -R "$TEMPLATE_REPO" -L 1 --json tagName --jq '.[0].tagName'`,
    falling back to `git ls-remote --tags --sort=-v:refname https://<host>/$TEMPLATE_REPO`
    for a GitLab-hosted template. If neither resolves, ask the user for the tag.
- **Major bumps aren't automatic.** If `TARGET`'s major exceeds the current ref's
  (e.g. `v0.19.x` → `v1.x`), stop and ask the user to confirm.
- If `TARGET` equals the current ref, nothing will change in `template.yml`. Say so
  and ask whether to re-run the sync anyway (to re-apply template content); stop
  unless they confirm.

## 3. Branch off the up-to-date default
`/update` may be invoked from any branch, but the PR must contain only the template
bump — so create the branch **before** editing anything. `Read`
**`${CLAUDE_PLUGIN_ROOT}/prompts/pr-base.md`** and follow it with
`BRANCH_PREFIX=rhiza_$TARGET`; it fetches `origin/$DEFAULT`, never pushes to it, and
leaves you on `$BRANCH`. Since the prefix already carries the tag, checking out an
existing `$BRANCH` is fine — a prior run made it off the same base. The tree was
confirmed clean in step 1, so nothing carries across.

## 4. Bump the ref and commit
On `$BRANCH`, set `ref:` (or `template-branch:`, whichever key is present) to
`"$TARGET"` in `.rhiza/template.yml`. Leave `profiles:`, `templates:`, `exclude:`,
`language:` and the rest exactly as they are — switching a platform profile is a
deliberate, separate change, not something a version bump should do.
```bash
git add .rhiza/template.yml
git commit -m "chore: bump rhiza to $TARGET"
```

## 5. Sync
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/sync.py" .
```
(**Keep the quotes.** In a source checkout `${CLAUDE_PLUGIN_ROOT}` is empty — fall
back to `scripts/sync.py`. `--no-project` stops `uv` resolving the target repo's env
for this stdlib-only script.)

**Capture the exit code before doing anything else:**
- **0** — clean; skip step 6.
- **1** — synced *with conflicts*; the lock is written and merged files are on disk.
  Expected, not fatal — go to step 6.
- **2** — real failure (dirty tree, invalid `template.yml`, git error). **Stop and
  report**; nothing was applied. Say that `$BRANCH` still holds the step-4 bump commit
  **unpushed**, so the user can retry or delete the branch — don't leave that implicit.

## 6. Resolve conflicts — take upstream
Only when step 5 exited 1. This step rewrites files the user did not author, so it is
a script, not your text editing — run it and read the exit code:
```bash
uv run --python 3.12 --no-project python \
    "${CLAUDE_PLUGIN_ROOT}/scripts/resolve_conflicts.py" .
```
It takes the **upstream (theirs)** side of every `<<<<<<< … ======= … >>>>>>>` block:
a rhiza-managed file is the template's to own, so local divergence in one is drift to
undo, not work to preserve.

It also deletes a `*.rej` that sits beside a file it just resolved. Those two artifacts
are the *same* change — `sync.py` tries `git apply -3`, which writes the reject, then
falls back to `git merge-file`, which writes markers holding that hunk's upstream side.
Taking the upstream side applies it; applying the reject too would apply it **twice**.

- **0** — every marker resolved, nothing outstanding. Continue.
- **1** — a `*.rej` remains with no resolved counterpart: a hunk git could not place at
  all. The script never applies one, because re-deriving where a hunk belongs is exactly
  the guess that corrupts a file. Show the listed rejects and ask the user how to
  proceed; do not stage a half-resolved tree.
- **2** — a malformed conflict block; **nothing was written**. Stop and report the file.

Then `git add` the resolved files (step 7's script does this from the lock, so you only
need to intervene for a file the script listed as outstanding).

## 7. Stage template-owned files only, then open the PR
The "template files only" rule is enforced by a script, not by you — don't hand-pick
paths, and never `git add --all`:
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/stage_synced.py" .
```
It reads the lock's `files` list, stages exactly that plus `template.yml`/the lock
(deletions included), and prints anything it deliberately left behind. Relay that
output. Exit **1** means no lock — the sync never ran; stop. Exit **2** is a git
failure; stop.

- **Anything reported as `left`** stays in the working tree. Name those paths in the
  PR body and the final report so the user decides — that's the expected outcome if a
  synced tool rewrote a repo-owned file.
- If nothing was staged, there's nothing to sync beyond the ref bump — say "already
  up to date after the bump" and continue with just the step-4 commit.
- Otherwise `git commit -m "chore: apply rhiza sync $TARGET"`.
- `git push --set-upstream origin "$BRANCH"` (this is also what pushes the step-4
  bump commit — until now the branch was local only).
- Open the PR/MR into `$DEFAULT`:
  ```bash
  uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/open_pr.py" \
    --base "$DEFAULT" --head "$BRANCH" \
    --title "chore: update rhiza to $TARGET" --body-file <BODY>
  ```
  It detects the platform from `origin` and issues `gh pr create` or `glab mr create`,
  which differ in subcommand *and* flag names. **This step used to be GitHub-only** —
  it detected GitLab, offered `gitlab-project`, then called `gh`. Don't hand-write
  either form; add `--update` to amend an existing request rather than erroring.
  - Body: the template repo + old ref → `$TARGET`, the count of files the sync
    changed, whether conflicts were resolved (taking upstream), anything left
    unstaged in the working tree, and a line noting that **no gates were run — run
    `/rhiza:quality` for a scorecard**.
- Exit **1** from the opener means the CLI is missing or failed. Don't treat that as
  fatal — the branch is already pushed; relay its note and print the compare URL.

## 8. Report and return
Short: `$TEMPLATE_REPO`, old ref → `$TARGET`, the branch, how many template files
changed, conflicts resolved (if any), anything deliberately left unstaged, and the
PR/MR URL. Close with the reminder that `/update` ran no gates — `/rhiza:quality`
produces the scorecard, and `/rhiza:status` shows what's now synced.

Then restore the invocation branch: `git checkout "$ORIG_BRANCH"`. Skip when
`ORIG_BRANCH` is empty (detached HEAD) or equals `$BRANCH`, and just report where you
are. Don't force it if the checkout fails — say you've left the tree on `$BRANCH` and
why.
