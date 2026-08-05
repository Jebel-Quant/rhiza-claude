# PR base + work branch (internal procedure)

> **Not a slash command.** This file lives in `prompts/`, which Claude Code does not
> scan for commands, so the user cannot invoke it. `/rhiza:init`, `/rhiza:update` and
> `/rhiza:release` read it to get a work branch based on an up-to-date remote default.

Goal: end with `$BRANCH` checked out, based on `origin/$DEFAULT`, so the caller's
commits land on a branch and the PR has a base to merge into.

**The default branch is never pushed to.** Not for a seed commit, not to bring it
into being on a brand-new repo. If it doesn't exist server-side, *the user* creates
it; if they don't, the caller stops. This is absolute — a protected default branch
must stay untouched, and a repo's first commit is the owner's to make.

Inputs from the caller: `$BRANCH_PREFIX` (`rhiza_init`, `rhiza_<TARGET>`, or
`rhiza_release_<TARGET>`), and — only needed on the brand-new path — `OWNER`, `NAME`,
and the chosen visibility.

## 1. Determine `DEFAULT`

`gh repo view --json defaultBranchRef --jq .defaultBranchRef.name` (GitHub) or
`git remote show origin` (either platform); fall back to `main`.

## 2. Make sure `origin/$DEFAULT` resolves

- **It already does** — just `git fetch origin "$DEFAULT"` so the branch is based on
  the current tip. Go to step 3.
- **It doesn't** — no `origin` at all, or an `origin` whose `$DEFAULT` isn't there
  yet. **Ask the user to create it** (`AskUserQuestion`); don't create or push it
  yourself. They should, on the platform, create `OWNER/NAME` with the chosen
  visibility and **initialise it with an empty README**, so `$DEFAULT` exists
  server-side. They can do it in-session:
  ```bash
  ! gh repo create "$OWNER/$NAME" --<private|public> --add-readme
  ```
  (or the GitLab equivalent that initialises a README). Then add the remote if absent
  (`git remote add origin <URL>`), `git fetch origin`, and re-read `$DEFAULT`.

  **If `origin/$DEFAULT` still doesn't resolve, stop the calling command** — report
  that it needs an empty-README-initialised default branch as the PR base. Do not
  fall back to pushing one.

## 3. Create the work branch

```bash
BRANCH="${BRANCH_PREFIX}_$(date +%Y%m%d)"
git checkout -b "$BRANCH" "origin/$DEFAULT"
```
- If that name already exists locally or on the remote, disambiguate with a time
  suffix: `${BRANCH_PREFIX}_$(date +%Y%m%d-%H%M%S)`. (For `/update`, whose prefix
  already carries the target tag, checking out the existing branch is fine instead —
  a prior run made it off the same base.)
- Uncommitted work that predates the calling command is left alone: it rides along or
  stays behind, untouched. Never stash or discard it.

Return `$BRANCH` and `$DEFAULT` to the caller.
