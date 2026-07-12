---
description: Bootstrap a rhiza-managed repo in the current folder (empty, or an existing git repo that isn't yet rhiza-managed) — git init if needed, ask whether it lives on GitHub or GitLab (auto-detecting an existing remote), ask owner/name/visibility, pick language (python/go) and template repo (default jebel-quant/rhiza or rhiza-go, with a reachability check), optionally scaffold the project (pyproject/src/tests, mkdocs.yml, a real starter README) via the bundled init_scaffold.py, validate the config, then put the scaffold and the first template sync on a `rhiza_init_<date>` branch and open a PR. Never pushes rhiza changes straight to the default branch.
argument-hint: "[repo name]  (optional; defaults to the current folder name)"
allowed-tools: Bash(git*), Bash(gh*), Bash(glab*), Bash(uvx*), Bash(make*), Bash(python3*), Bash(cat*), Bash(ls*), Bash(basename*), Bash(pwd*), Bash(date*), Read, Write, AskUserQuestion
---

You are running `/init` in the **current working directory**. Goal: turn this
folder into a fresh **rhiza-managed** repository — initialise git (if it isn't
already), decide where it lives (GitHub or GitLab), scaffold the `.rhiza/` config
for that platform, apply the rhiza template with a first sync, and **open a PR**
with that work. After it merges, the repo is a normal rhiza-managed repo where
`/boost`, `/quality`, and `make sync` all work.

The folder may be **empty** or may **already contain a git repo** (a `.git/` you
`git init`'d earlier, possibly with commits and even an `origin` remote) — as
long as it isn't rhiza-managed yet. Detect which case you're in and adapt: never
re-init an existing repo, and never clobber an existing remote.

**Never push rhiza changes to the default branch.** The `.rhiza` scaffold and the
template sync (which can be hundreds of files, including CI) go on a dedicated
`rhiza_init_<date>` branch and are delivered as a PR, so they get reviewed — this
matters most in an existing repo whose default branch may be protected. The only
thing that ever lands on the default branch directly is the empty initial commit
that seeds a brand-new repo (step 6), because a PR needs a base branch to exist.

Argument (optional): `$ARGUMENTS` — the repository name. If empty, default to the
current folder's basename.

**How the first sync bootstraps.** `.rhiza/rhiza.mk` (the real `make` API) is
delivered *by* the template sync. The scaffolder in step 8 writes a small
**bootstrap `Makefile`** whose `sync` target runs `uvx rhiza sync .` and is active
only until that first sync writes `.rhiza/rhiza.mk` — so `make sync` works even on
a brand-new repo, and every sync afterward uses the template's own target.

Work through these steps. Stop and report if a precondition fails.

## 1. Preconditions — and detect the starting state
- **Already rhiza-managed?** If `.rhiza/template.yml` exists, abort and point at
  `/boost` — this command is for repos that aren't managed yet.
- **Is there already a git repo?** Run `git rev-parse --is-inside-work-tree`
  (ignore its error if absent). Record `HAS_GIT` accordingly. If yes, capture the
  existing state — you'll reuse it, not recreate it:
  - current branch — `git branch --show-current` (may be empty on an
    unborn branch with no commits);
  - whether any commits exist — `git rev-list -n1 --all` (empty output ⇒ no
    commits yet);
  - existing `origin` remote, if any — `git remote get-url origin`
    (record as `EXISTING_ORIGIN`).
- **Folder contents.** Run `ls -A`. If it contains files beyond an expected
  `.git/` and ordinary dotfiles, list them and ask the user (`AskUserQuestion`)
  whether to proceed — `/init` layers `.rhiza/` config plus a large template sync
  on top of whatever is here. Do not proceed without a yes.
- Confirm `uvx` is available (`uvx --version`). It's required for the bootstrap
  sync in step 9. If missing, you can still scaffold, branch, and (for a
  brand-new repo) create the remote — but warn that the user must install `uv`
  and run the first sync manually before the PR is meaningful.

## 2. git init (only if needed)
- If `HAS_GIT` is false, `git init -b main` (default branch `main`). If the
  installed git is too old for `-b`, run `git init` then
  `git symbolic-ref HEAD refs/heads/main`.
- If `HAS_GIT` is true, **skip init entirely** — the repo already exists. Keep its
  current branch; do not rename or reset it.

> **Shortcut for a fully-fledged repo.** If `EXISTING_ORIGIN` was found in
> step 1, the repo already exists remotely — its platform, owner, and name are
> all determined by that remote, so **skip the questions in steps 3 and 4
> entirely**. Derive everything from the URL, report what you detected, and go
> straight to step 5:
> - platform/profile from the host (`github.com` → GitHub/`github-project`;
>   `gitlab.com` or a self-hosted GitLab host → GitLab/`gitlab-project`);
> - `OWNER`/`NAME` from the URL path;
> - no `VISIBILITY` — the remote already has one; `/init` won't change it.
>
> Steps 3 and 4 below are **only** for the no-remote (empty-folder) case. Note
> that opening the PR (step 10) still needs the platform CLI (`gh`/`glab`) even
> on this path; if it's unavailable, `/init` pushes the branch and hands you a
> "create PR" URL instead.

## 3. Choose the platform (GitHub vs GitLab)
No `origin` remote to go on, so ask where the repo shall live. Present the menu
with `AskUserQuestion`, **GitHub first and marked "(Recommended)"**, GitLab
second:
- **GitHub** → platform `github`, profile `github-project`, CLI `gh`.
- **GitLab** → platform `gitlab`, profile `gitlab-project`, CLI `glab`.

Verify the chosen platform's CLI is installed and authenticated
(`gh auth status` / `glab auth status`). If it isn't, tell the user how to fix it
(`gh auth login` / `glab auth login`) and stop before creating anything remote —
but you may still complete the local scaffold on the work branch (steps 4–9) and
report that the remote/push/PR (steps 6–10) are pending auth.

## 4. Collect repo details (ask each run)
Gather via `AskUserQuestion` (offer sensible defaults, let the user override):
- **Owner / namespace** — the GitHub org-or-user, or GitLab group/namespace, that
  will own the repo. No safe default; ask.
- **Repository name** — default to `$ARGUMENTS` if given, else `basename "$PWD"`.
- **Visibility** — private (recommended default) or public.

Hold these as `OWNER`, `NAME`, `VISIBILITY` for the remaining steps. The full
slug is `OWNER/NAME`.

## 5. Choose the template source and version
Runs on **both** paths (a repo can be Go even when it already has a remote).

- **Language.** Ask (`AskUserQuestion`, default **python**): `python` or `go`. It
  selects the default template repo and the scaffolding shape in step 9.
- **Template repository** — hold as `TEMPLATE_REPO`:
  - default by language: `jebel-quant/rhiza` (python), `jebel-quant/rhiza-go` (go);
  - offer to override with a custom `owner/repo`, or to pick from the
    rhiza-tagged repos (the same set `/rhiza:repos` lists —
    `gh search repos --topic rhiza --json fullName`). Keep the default unless the
    user chooses otherwise.
- **Reachability check.** Before writing anything, confirm the chosen repo exists
  and is readable: `git ls-remote --exit-code https://<host>/$TEMPLATE_REPO`
  (host = `github.com` or `gitlab.com` per the platform). If it's unreachable,
  stop and report — don't scaffold a `template.yml` that points at a repo that
  isn't there. (If `git` can't check, warn and continue rather than hard-fail.)
- **Template content version** — hold as `TARGET`: latest release of
  `$TEMPLATE_REPO`, `gh release list -R "$TEMPLATE_REPO" -L 1 --json tagName --jq '.[0].tagName'`
  (falls back to `git ls-remote --tags` for a GitLab-hosted template repo). If
  neither works, ask the user for the tag (e.g. `v1.1.3`).

Note: `.rhiza/.rhiza-version` (the rhiza **tool** version, distinct from `TARGET`)
is *not* written here — the sync in step 9 delivers it, matching `rhiza init`.

## 6. Establish the remote and the default branch
Every rhiza change goes on a branch (step 7) and out as a PR (step 10), so first
make sure there's a remote **and** a non-empty default branch to be the PR base.
Determine the default branch name `DEFAULT` (existing repo:
`git remote show origin` / `gh repo view --json defaultBranchRef`; brand-new:
`main`).

- **Brand-new repo (no `origin`, no commits):**
  - Seed the default branch with an **empty** initial commit so it can serve as a
    PR base: `git commit --allow-empty -m "chore: initialise repository"`.
  - Create the remote and push only `DEFAULT`:
    - **GitHub:**
      `gh repo create "$OWNER/$NAME" --<private|public> --source=. --remote=origin --push`
    - **GitLab:** `glab repo create "$OWNER/$NAME" --<private|public>`, then
      `git remote add origin <the URL glab prints>` and
      `git push -u origin "$DEFAULT"`.
  - If creation fails because the name is already taken remotely, stop and report
    — do not overwrite or force-push. (If it's actually *your* repo, add it as
    `origin` and re-run; `/init` will take the existing-remote path.)
- **Existing repo with `origin`:** don't create anything. Fetch so the branch is
  based on the current tip: `git fetch origin`. If the repo had commits on an
  unpushed local default branch but no remote default yet, push it first
  (`git push -u origin "$DEFAULT"`) so the PR has a base.

## 7. Create the work branch
- `BRANCH=rhiza_init_$(date +%Y%m%d)`. If that branch already exists locally or on
  the remote, disambiguate with a time suffix: `rhiza_init_$(date +%Y%m%d-%H%M%S)`.
- Branch off the up-to-date default — **never commit the rhiza work onto
  `DEFAULT`**:
  - existing remote: `git checkout -b "$BRANCH" "origin/$DEFAULT"`;
  - brand-new (default only exists locally so far): `git checkout -b "$BRANCH"`.

## 8. Scaffold the project (bundled script) and commit (on the branch)
**This is a thin wrapper around the bundled `scripts/init_scaffold.py`** — a
deterministic, stdlib-only port of what `rhiza init` used to scaffold (the whole
point is to let `rhiza init` be retired). It writes only the files that the sync
in step 9 does **not** own: `.rhiza/template.yml`, a bootstrap `Makefile`, and —
for Python — `pyproject.toml`, `src/<pkg>/`, `tests/test_main.py`, `mkdocs.yml`,
and a real starter `README.md` (running `uv lock` when `uv` is present). It
creates **only what's missing** and never overwrites. Do not hand-write these
files yourself — run the script.

First, offer the optional pieces (`.rhiza/template.yml` + `Makefile` are always
written; these are the extras). Ask with an `AskUserQuestion` **multi-select**
(`multiSelect: true`) — recommend all for a brand-new empty repo, fewer if the
repo already has code:
- **package** — `pyproject.toml` + `src/<pkg>/` + `tests/` (Python only);
- **mkdocs** — `mkdocs.yml` that inherits the synced `docs/mkdocs-base.yml`;
- **readme** — a real starter `README.md`.

Build the `--components` value from the selection (comma-joined; empty string if
none). Then run the script with the plugin-root path (**keep the quotes**;
falls back to the repo-relative `scripts/init_scaffold.py` in a source checkout):
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init_scaffold.py" . \
  --project-name "$NAME" --owner "$OWNER" \
  --host <github|gitlab> --language <python|go> \
  --template-repo "$TEMPLATE_REPO" --ref "$TARGET" \
  --components <selected>
```
Relay its `created`/`skipped`/`notes` output (for `go` it prints the
`go mod init` hint). Then commit:
- `git add --all`
- `git commit -m "chore: scaffold rhiza-managed project"`

## 9. Bootstrap the first sync (on the branch)
The scaffolder wrote a bootstrap `Makefile`, so run:
```bash
make sync
```
(equivalent to `uvx rhiza sync .`, which you can run directly if `make` is
unavailable). This materialises the template for the chosen profile —
`.rhiza/rhiza.mk`, CI workflows (`.github/workflows/*` for GitHub or
`.gitlab-ci.yml` for GitLab), `docs/mkdocs-base.yml`, `.rhiza/.rhiza-version`,
and the rest.
- On a truly **empty** folder there's nothing to conflict with, so a non-zero
  exit is unexpected — capture the output and report it rather than papering
  over it.
- If the folder **already had files**, the sync may report conflicts or leave
  `.rej` files where a template file overlaps something you already had. Resolve
  them the same way `/boost` does — take the **upstream (template) side** — then
  continue; if anything is ambiguous, stop and show the conflicting files rather
  than guessing.

Then commit the sync output:
- `git add --all`
- If `git diff --cached --name-only` is non-empty:
  `git commit -m "chore: apply rhiza sync <TARGET>"`
- Else report "sync produced no files" (unexpected — flag it).

### Validate the configuration
Before pushing, confirm the config and scaffold are valid — this is what
`rhiza init` did at the end, so don't skip it. With the Makefile now in place:
```bash
make validate
```
(or `uvx rhiza validate .`, or the plugin's stdlib validator
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate.py"`). If validation fails, stop
and show the errors rather than opening a PR on a broken config.

## 10. Push the branch and open the PR
- `git push -u origin "$BRANCH"`.
- Open a PR/MR from `$BRANCH` into `$DEFAULT` with the platform CLI:
  - **GitHub:** `gh pr create --base "$DEFAULT" --head "$BRANCH" --title "chore: initialise rhiza-managed repo (<TARGET tag>)" --body-file <BODY>`
  - **GitLab:** `glab mr create --source-branch "$BRANCH" --target-branch "$DEFAULT" --title "chore: initialise rhiza-managed repo (<TARGET tag>)" --description-file <BODY>`
  - The body should note: platform/profile, language + template repo + tag,
    that it seeds the repo as rhiza-managed, and that CI arrives with this PR.
- If the platform CLI is unavailable or unauthenticated, don't fail — the branch
  is already pushed; print the branch name and the "create a PR" compare URL so
  the user can open it in the browser.

## 11. Report
Summarise concisely: the repo slug (`OWNER/NAME`) and its URL, platform + profile,
visibility (for a new repo), language + template repo + tag, the work branch name,
the commits on it, the files the scaffolder created (and any skipped as
already-present), the count of files the sync added, and the **PR URL** (or the
manual compare URL if the CLI was unavailable). Point the user at next steps:
review + merge the PR, then flesh out the docs with `/revisit` and run `/quality`
for the initial scorecard.
