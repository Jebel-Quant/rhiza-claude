---
description: Make the current folder a rhiza-managed repo. It writes exactly one file itself — `.rhiza/template.yml`, the pointer at a template repository and pinned ref — and delegates everything else to internal procedures under prompts/ — install-uv, pr-base (work branch off an untouched default), skeleton (uv init --lib + the pyproject shape the template's gates require, which itself applies python-version), and license. If a `.rhiza/` directory already exists it hands off to /update instead and never touches template.yml. It detects (or asks) GitHub vs GitLab, picks the template repo (default jebel-quant/rhiza, reachability-checked) and its latest release as the initial pin, then opens a PR. It runs no sync and no gates — the template content (CI, Makefile, rhiza.mk, docs base) arrives when the user runs /update after this PR merges. Never pushes to the default branch.
argument-hint: "[repo name]  (optional; defaults to the current folder name)"
allowed-tools: Bash(git*), Bash(gh*), Bash(glab*), Bash(uv*), Bash(curl*), Bash(brew*), Bash(ls*), Bash(basename*), Bash(pwd*), Bash(date*), Read, Write, Edit, AskUserQuestion, Skill
---

You are running `/init` in the **current working directory**. Goal: make this folder
a **rhiza-managed** repo and deliver it as a **PR**.

**`/init` writes exactly one file itself** — `.rhiza/template.yml`, the pointer saying
which template repository this repo follows and at which ref. Everything else it
`Read`s from the procedure that owns it, so each concern has one source of truth and
`/init` stays a coordinator rather than a second implementation:

| what | procedure | step |
| --- | --- | --- |
| `uv` on the machine | `prompts/install-uv.md` | 1 |
| work branch off an untouched default | `prompts/pr-base.md` | 4 |
| skeleton + the `pyproject.toml` shape the gates need | `prompts/skeleton.md` (applies `prompts/python-version.md`) | 6 |
| SPDX metadata + the `LICENSE` file | `prompts/license.md` | 6 |

Those are **internal procedures, not slash commands** — deliberately outside
`commands/` so the user can't invoke them. `Read` each at the step that calls for it
(`${CLAUDE_PLUGIN_ROOT}/prompts/<name>.md`; in a source checkout the variable is
empty, so use the repo-relative path) and follow it as written. **Never re-implement
one inline** — no hand-rolled `pyproject.toml` edits, no `LICENSE` writing, no
`uv init` of your own.

**No sync, no gates.** Bootstrapping is two PRs: **#1 (`/init`) makes the repo
rhiza-managed; #2 (`/update`, after #1 merges) pulls the template content.** Keeping
the sync out of `/init` stops it re-implementing `/update` and drifting from it. The
user runs `/docs` for `README.md`/`CLAUDE.md`/`mkdocs.yml` and `/quality` for a
scorecard.

Argument (optional): `$ARGUMENTS` — the repository name; default `basename "$PWD"`.
Hold as `NAME`.

Work through these steps. Stop and report if a precondition fails.

## 1. Preconditions

- **Already rhiza-managed? → hand off.** If a `.rhiza/` directory exists
  (`test -d .rhiza`), **invoke the `update` command via the Skill tool** and stop.
  Don't write or touch anything under `.rhiza/` yourself — bumping an existing config
  is `/update`'s job. This holds even for a stray `.rhiza/` with no `template.yml`.
- **`uv`** — `Read` `prompts/install-uv.md` and follow it, every run. A one-line
  no-op when `uv` is present; otherwise it installs it. If `uv --version` still fails,
  stop.
- **Git** — `git rev-parse --is-inside-work-tree` (ignore the error if absent). No
  repo ⇒ `git init -b main`. If a repo exists, record any `origin` as
  `EXISTING_ORIGIN`.

You don't need to vet the folder's contents: everything `/init` runs is additive and
never overwrites, so an empty folder and a mature repo are the same case.

## 2. Platform, owner, name

> **If `EXISTING_ORIGIN` was found**, derive everything from that URL and **ask
> nothing**: platform from the host (`github.com` → GitHub/`github-project`; a GitLab
> host → GitLab/`gitlab-project`), `OWNER`/`NAME` from the path. Report what you
> detected and go to step 3.

Otherwise ask (`AskUserQuestion`): **platform** (GitHub first, marked
"(Recommended)"; GitLab second), **owner/namespace** (no safe default), **repository
name** (default `NAME`), **visibility** (private recommended).

Verify the platform CLI is authenticated — don't pick the binary yourself:
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/platform_cli.py" \
  auth-status
```
Exit **0** is authenticated. Exit **1** means the CLI is absent or logged out; its note
says which. Tell the user the fix (`gh auth login` / `glab auth login`) — you may still
complete the local work and report that the remote steps are pending auth.

## 3. Template source and version

- **Language** — ask (`AskUserQuestion`, default **python**): `python`, `rust` or `go`.
  It picks the default template repo, the `language:` key in the pointer, and the
  profile: `rust` gets the namespaced `rust-github-project` / `rust-gitlab-project`,
  the others the unprefixed pair.
- **`TEMPLATE_REPO`** — default `jebel-quant/rhiza` (python **and rust** — that
  template is multi-language, layering a `rust-core` toolchain bundle on a neutral
  `core`) or `jebel-quant/rhiza-go` (go, a separate fork); offer to override with any
  `owner/repo`, or to pick from `gh search repos --topic rhiza --json fullName`.
- **Rust needs a recent enough pin.** The `rust-*` profiles only exist from the
  `jebel-quant/rhiza` release that introduced them. If `$TARGET` predates it the first
  `/update` fails with "Profile 'rust-github-project' was not found" — check with
  `git ls-remote --tags` or just pin the latest release, which step 3's `TARGET` does
  anyway.
- **Reachability** — `git ls-remote --exit-code https://<host>/$TEMPLATE_REPO`. If
  unreachable, **stop** — don't write a pointer at a repo that isn't there. (If `git`
  can't check, warn and continue.)
- **`TARGET`** — its latest release:
  `gh release list -R "$TEMPLATE_REPO" -L 1 --json tagName --jq '.[0].tagName'` (fall
  back to `git ls-remote --tags` for a GitLab-hosted template; else ask). Just the
  **initial pin** — `/update` bumps it later, and nothing is synced from it here.

## 4. Work branch

`Read` `prompts/pr-base.md` and follow it with `BRANCH_PREFIX=rhiza_init`, passing
`OWNER`/`NAME`/visibility for the brand-new-repo path. It settles `$DEFAULT`, gets
`origin/$DEFAULT` to exist (asking *the user* to create the repo with an empty README
rather than ever pushing to the default branch), and leaves you on `$BRANCH`. If it
can't, it stops `/init` — don't work around that.

## 5. Write the pointer

`scripts/init_scaffold.py` writes `.rhiza/template.yml` and only that, only if absent:
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/init_scaffold.py" . \
  --host <github|gitlab> --language <python|rust|go> \
  --template-repo "$TEMPLATE_REPO" --ref "$TARGET"
```

> **`--host` is about *this* repo, not the template.** It selects the profile, so a
> GitLab repo gets GitLab's CI. Where the *template* lives is a separate flag,
> `--template-host`, which defaults to GitHub — where the rhiza templates are. Only
> pass it when the template itself is GitLab-hosted. Conflating the two emitted
> `template-host: gitlab` for every GitLab repo, and the first sync then tried to clone
> `jebel-quant/rhiza` from gitlab.com and failed with "could not read Username".
Relay its `created`/`skipped` output, then commit it alone:
```bash
git add .rhiza/template.yml
git commit -m "chore: point repo at $TEMPLATE_REPO@$TARGET"
```

## 6. Skeleton, then license

Skip both for `go` — `prompts/skeleton.md` covers python and rust only, and
`rhiza-go` has its own scaffolding.

- `Read` `prompts/skeleton.md` and follow it, telling it the language. **Not
  optional:** the template never ships a manifest, so without one `/update`'s gates
  fail outright — on python `make test` depends on `install` (a `uv sync`) and the
  synced `.rhiza/tests/test_pyproject.py` asserts a specific `[project]` shape; on
  rust every `cargo` target needs a `Cargo.toml`. Carry `OWNER`/`NAME`/host in from
  step 2 so nothing is re-asked; let it ask for the description (and, on python, the
  Python version), which are its own to own.
- **Verify the manifest exists** — `test -f pyproject.toml` (python) or
  `test -f Cargo.toml` (rust). The procedure checks too, but check again: if it's
  missing, **stop and report**. Don't hand-write one, and don't commit or open a PR
  on a repo whose skeleton step failed.
- `Read` `prompts/license.md` and follow it. Skip only if the user wants the repo
  unlicensed.
- Commit what they produced:
  ```bash
  git add --all
  git commit -m "chore: add project skeleton + license metadata"
  ```
  A clean `git status` here just means both found everything already in place — say so
  and move on; a pointer-only PR is fine.

## 7. Push and open the PR

```bash
git push -u origin "$BRANCH"
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/platform_cli.py" \
  pr-create --base "$DEFAULT" --head "$BRANCH" \
  --title "chore: make repo rhiza-managed" --body-file <BODY>
```
It detects the platform from `origin` and issues the right call — `gh pr create` or
`glab mr create`, which differ in subcommand, flag names *and* whether a body can come
from a file at all. Don't hand-write either: that mapping lived in prose once, and
`/update` shipped calling `gh` on GitLab repos. Add `--dry-run` to see the command
without creating anything.

Keep the body short: template repo + pinned ref + profile, what the PR contains, and
that **after merging the user runs `/update`** to pull the template content. If the
CLI is missing or unauthenticated, don't fail — the branch is pushed; print it and the
compare URL.

## 8. Report

The repo slug and URL, platform + profile, language, template repo + pinned ref, the
branch, and the **PR URL** (or compare URL). Then one line each for what the
procedures did: the pointer file, what `/skeleton` created or filled in plus the
Python version applied, and which license was written. State what is **not** in this
PR: no CI, no `Makefile`, no `.rhiza/rhiza.mk`, no docs, no gates run.

Next steps: **review + merge**, then **run `/update`** (syncs the template, opens
PR #2); add your first module — the package is empty by design; `/docs` for
`README.md`/`CLAUDE.md`/`mkdocs.yml`; `/quality` anytime for a scorecard.
