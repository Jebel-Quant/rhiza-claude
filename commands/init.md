---
description: Bootstrap a rhiza-managed repo in the current folder. If it's already rhiza-managed (a `.rhiza/` directory exists) it hands off to `/update` and never touches template.yml. Otherwise it wraps `uv init --lib` to create the standard Python skeleton (git repo + pyproject.toml + src/<pkg>/ + README), seeds a starter module and test via `/new` so the coverage gate passes, asks GitHub vs GitLab (auto-detecting an existing remote) and owner/name/visibility, picks the template repo (default jebel-quant/rhiza, with a reachability check), scaffolds the rhiza-only config (.rhiza/template.yml + a bootstrap Makefile, and optionally mkdocs.yml) via init_scaffold.py, runs the first template sync, validates, runs the test suite, then opens a PR on a `rhiza_init_<date>` branch. Never pushes rhiza changes straight to the default branch.
argument-hint: "[repo name]  (optional; defaults to the current folder name)"
allowed-tools: Bash(git*), Bash(gh*), Bash(glab*), Bash(uv*), Bash(uvx*), Bash(make*), Bash(python3*), Bash(cat*), Bash(ls*), Bash(basename*), Bash(pwd*), Bash(date*), Read, Write, Edit, AskUserQuestion, Skill
---

You are running `/init` in the **current working directory**. Goal: turn this
folder into a fresh **rhiza-managed** repository — create the standard project
skeleton with `uv`, decide where it lives (GitHub or GitLab), scaffold the
`.rhiza/` config, apply the rhiza template with a first sync, and **open a PR**
with that work. After it merges, the repo is a normal rhiza-managed repo where
`/update`, `/quality`, and `make sync` all work.

**`/init` wraps `uv init` for the project skeleton.** Rather than hand-rolling a
`pyproject.toml`/`src/`/`README.md`, it runs `uv init --lib` (step 2), which also
initialises the git repo. The bundled scaffolder then adds only the rhiza-specific
files `uv` doesn't provide (`.rhiza/template.yml`, a bootstrap `Makefile`, and
optionally `mkdocs.yml`). You therefore do **not** need to be in a git repo first
— `uv init` creates one. The folder may still be empty, or already contain a git
repo (even with commits and an `origin` remote) — adapt to which it is, and never
clobber existing work or a remote.

**`/init` is only for repos that aren't rhiza-managed yet.** If a `.rhiza/`
directory already exists, `/init` hands off to `/update` (bringing the template to
its latest version) instead of bootstrapping — it never touches an existing
`.rhiza/template.yml`. See step 1.

**Never push rhiza changes to the default branch.** The `.rhiza` scaffold and the
template sync (which can be hundreds of files, including CI) go on a dedicated
`rhiza_init_<date>` branch and are delivered as a PR, so they get reviewed — this
matters most in an existing repo whose default branch may be protected. The only
thing that ever lands on the default branch directly is the initial skeleton
commit that seeds a brand-new repo (step 6), because a PR needs a base branch.

Argument (optional): `$ARGUMENTS` — the repository name. If empty, default to the
current folder's basename.

**How the first sync bootstraps.** `.rhiza/rhiza.mk` (the real `make` API) is
delivered *by* the template sync. The scaffolder in step 8 writes a small
**bootstrap `Makefile`** whose `sync` target runs `uvx rhiza sync .` and is active
only until that first sync writes `.rhiza/rhiza.mk` — so `make sync` works even on
a brand-new repo, and every sync afterward uses the template's own target.

Work through these steps. Stop and report if a precondition fails.

## 1. Preconditions — and detect the starting state
Run these checks first, in order:
- **Already rhiza-managed? → hand off to `/update`.** Check for a `.rhiza/`
  directory (`test -d .rhiza`). If it exists, the repo is already managed, so
  `/init` does **not** bootstrap it: **invoke the `update` command via the Skill
  tool** to bring the template to its latest version, then stop — `/init` is done.
  On this path, do **not** scaffold, and do **not** touch `.rhiza/template.yml`
  (or anything under `.rhiza/`) yourself: bumping an existing config is
  `/update`'s job. This holds even for a stray `.rhiza/` without a `template.yml`.
- **Capture any existing git state.** Run `git rev-parse --is-inside-work-tree`
  (ignore its error if absent) and record `HAS_GIT`. `/init` does not *require* a
  repo — step 2's `uv init` creates one — but if a repo already exists, capture
  what you'll reuse rather than recreate:
  - current branch — `git branch --show-current` (may be empty on an unborn branch);
  - whether any commits exist — `git rev-list -n1 --all` (empty ⇒ none yet);
  - existing `origin` remote, if any — `git remote get-url origin`
    (record as `EXISTING_ORIGIN`).
- **Folder contents.** Run `ls -A`. If it contains files beyond an expected
  `.git/` and ordinary dotfiles, list them and ask the user (`AskUserQuestion`)
  whether to proceed — `/init` layers a skeleton, `.rhiza/` config, and a large
  template sync on top of whatever is here. Do not proceed without a yes.
- Confirm `uv` and `uvx` are available (`uv --version`). `uv` is required for the
  skeleton in step 2 and `uvx` for the bootstrap sync in step 9. If missing, stop
  and tell the user to install `uv` first.

## 2. Bootstrap the project skeleton with `uv init`
First settle the two things the skeleton needs — they have safe defaults, so you
can decide them here without a heavy prompt:
- `NAME` — the project/package name: `$ARGUMENTS` if given, else `basename "$PWD"`.
- **Language** — ask (`AskUserQuestion`, default **python**): `python` or `go`.
  Hold as `LANGUAGE`; it also selects the default template repo in step 5.

Then create the skeleton:
- **Python** — if there's **no** `pyproject.toml` yet, run:
  ```bash
  uv init --lib --name "$NAME"
  ```
  This creates the git repo (if absent), `pyproject.toml`, `src/<pkg>/__init__.py`
  (+ `py.typed`), `README.md`, `.gitignore`, and `.python-version`. If a
  `pyproject.toml` **already** exists, do **not** run `uv init` (it refuses) —
  just ensure a git repo exists (`git init -b main` when `HAS_GIT` is false) and
  keep the existing files untouched.
- **Go** — `uv` doesn't apply; ensure a git repo exists (`git init -b main` when
  `HAS_GIT` is false). The Go module is set up from the `go mod init` hint the
  scaffolder prints in step 8.

`uv init` creates **no `tests/`**, so a Python skeleton alone has nothing to cover
and would fail the coverage gate in step 9. Seed a starter module and its test by
**invoking the `new` command via the Skill tool** (Python only):
- run `new main` — it adds `src/<pkg>/main.py` (a docstringed placeholder) and a
  mirrored test file. That gives the repo one tested module so `make test` starts
  green. Skip this when the folder already had source of its own.

> **Shortcut for a fully-fledged repo.** If `EXISTING_ORIGIN` was found in step 1,
> the repo already exists remotely — its platform, owner, and name are all
> determined by that remote, so **skip the questions in steps 3 and 4 entirely**.
> Derive everything from the URL, report what you detected, and go straight to
> step 5:
> - platform/profile from the host (`github.com` → GitHub/`github-project`;
>   `gitlab.com` or a self-hosted GitLab host → GitLab/`gitlab-project`);
> - `OWNER`/`NAME` from the URL path;
> - no `VISIBILITY` — the remote already has one; `/init` won't change it.
>
> Steps 3 and 4 below are **only** for the no-remote case. Note that opening the
> PR (step 10) still needs the platform CLI (`gh`/`glab`) even on this path; if
> it's unavailable, `/init` pushes the branch and hands you a "create PR" URL.

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
- **Repository name** — default to the `NAME` you settled in step 2. If the user
  changes it now, note that the skeleton package under `src/` still carries the
  original name (renaming a package is a manual follow-up).
- **Visibility** — private (recommended default) or public.

Hold these as `OWNER`, `NAME`, `VISIBILITY` for the remaining steps. The full
slug is `OWNER/NAME`.

## 5. Choose the template source and version
`LANGUAGE` was already chosen in step 2; use it to pick the default template repo.
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

## 6. Establish the remote and the default branch
Every rhiza change goes on a branch (step 7) and out as a PR (step 10), so first
make sure there's a remote **and** a non-empty default branch to be the PR base.
Determine the default branch name `DEFAULT` (existing repo:
`git remote show origin` / `gh repo view --json defaultBranchRef`; brand-new:
`main`).

- **Brand-new repo (no `origin`):**
  - Commit the skeleton `uv init` (and the starter module) produced so the default
    branch has a real base: `git add -A && git commit -m "chore: initialise project skeleton"`.
    (If `uv init` already committed, skip.)
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

## 8. Scaffold the rhiza-only config (bundled script) and commit (on the branch)
**This is a thin wrapper around the bundled `scripts/init_scaffold.py`** — a
deterministic, stdlib-only script that writes only the rhiza-specific files `uv`
does **not** provide and that the sync in step 9 does **not** own:
`.rhiza/template.yml`, a bootstrap `Makefile`, and — optionally — `mkdocs.yml`
(inheriting the synced `docs/mkdocs-base.yml`). The project skeleton
(`pyproject.toml`, `src/`, `README.md`) already came from `uv init` in step 2, so
the scaffolder no longer writes it. It creates **only what's missing** and never
overwrites.

Offer the one optional piece (`.rhiza/template.yml` + `Makefile` are always
written): ask with an `AskUserQuestion` whether to add **mkdocs** (`mkdocs.yml`).
Build the `--components` value (`mkdocs` or empty), then run the script with the
plugin-root path (**keep the quotes**; falls back to the repo-relative
`scripts/init_scaffold.py` in a source checkout):
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/init_scaffold.py" . \
  --project-name "$NAME" --owner "$OWNER" \
  --host <github|gitlab> --language <python|go> \
  --template-repo "$TEMPLATE_REPO" --ref "$TARGET" \
  --components <mkdocs|>
```
Relay its `created`/`skipped`/`notes` output (for `go` it prints the
`go mod init` hint). Then commit:
- `git add --all`
- `git commit -m "chore: scaffold rhiza config"`

## 9. Bootstrap the first sync (on the branch)
Run the first sync with the plugin's **bundled, stdlib-only** porter — the same
`scripts/sync.py` that `/update` uses. Do **not** use `uvx rhiza sync` (or the
bootstrap `Makefile`'s `make sync`, which shells out to it): the `rhiza` CLI is
being retired, and the bundled script is its stdlib replacement.
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sync.py" .
```
(falls back to the repo-relative `scripts/sync.py` in a source checkout). This
materialises the template for the chosen profile —
`.rhiza/rhiza.mk`, CI workflows (`.github/workflows/*` for GitHub or
`.gitlab-ci.yml` for GitLab), `docs/mkdocs-base.yml`, and the rest.
- On a fresh skeleton there's little to conflict with, so a non-zero exit is
  unexpected — capture the output and report it rather than papering over it.
- If the folder **already had files**, the sync may report conflicts or leave
  `.rej` files where a template file overlaps something you already had. Resolve
  them the same way `/update` does — take the **upstream (template) side** — then
  continue; if anything is ambiguous, stop and show the conflicting files rather
  than guessing.

Then commit the sync output:
- `git add --all`
- If `git diff --cached --name-only` is non-empty:
  `git commit -m "chore: apply rhiza sync <TARGET>"`
- Else report "sync produced no files" (unexpected — flag it).

### Validate the configuration
Before pushing, confirm the config and scaffold are valid by **invoking the
`validate` command via the Skill tool** — it wraps the bundled stdlib
`scripts/validate.py` (again, not `uvx rhiza validate`, which is retiring). If
validation fails, stop and show the errors rather than opening a PR on a broken
config.

### Run the test suite
Then exercise the suite the sync just delivered — the template's `.rhiza/tests/`
checks (structural ones like `test_pyproject.py`, `test_docstrings`,
`test_readme_validation`) plus any project tests — so the PR isn't opened on a
repo that can't pass its own gates:
```bash
make test
```
(bare `uvx pytest` if `make` is unavailable). `make test` also enforces a coverage
gate; the starter module + test seeded in step 2 is what keeps a fresh Python repo
green. Triage a non-zero exit **by cause**:

- **`uv init`'s generic `pyproject.toml` fails a `.rhiza/tests/` structural check**
  — e.g. `test_pyproject.py` wants a field `uv init` didn't add. **Enhance the
  file to satisfy the check**: merge in the missing keys/sections (`Read` it, then
  `Edit` in the additions), preserving what's there — then re-run `make test`.
  Editing this locally-owned `pyproject.toml` is expected here.
- **A genuine project-test failure, or a coverage shortfall from the user's own
  untested code** (only possible when the folder already had source) — don't
  paper over it and don't block on it. Record it clearly in the report and the PR
  body as a known-red gate the user must address, and continue to the PR.
- **A brand-new / freshly-seeded scaffold going red** — unexpected; capture the
  output and report it rather than opening the PR.

If you enhanced any file to get the suite green, commit that fix on the branch:
- `git add --all`
- `git commit -m "chore: align pyproject with rhiza template tests"`

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
the commits on it, the skeleton `uv init` produced and the starter module seeded,
the rhiza files the scaffolder created (and any skipped), the count of files the
sync added, the **test-suite result** (`make test` — green, or any known-red gate
carried into the PR per step 9), and the **PR URL** (or the manual compare URL if
the CLI was unavailable). Point the user at next steps: review + merge the PR,
then flesh out the docs with `/revisit` and run `/quality` for the initial
scorecard.
