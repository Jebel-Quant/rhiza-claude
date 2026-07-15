---
description: Create or revisit the current repo's README.md (with the full standard rhiza badge set), CLAUDE.md, and mkdocs.yml, auto-detecting platform, owner/repo, and project metadata; preserve hand-written content, fill gaps, refresh badges, and sync the README's `make help` target list.
argument-hint: "[readme | claude | mkdocs | all]  (optional; defaults to all)"
allowed-tools: Bash(git*), Bash(gh*), Bash(glab*), Bash(grep*), Bash(find*), Bash(cat*), Bash(sed*), Bash(head*), Bash(make*), Bash(python3*), Bash(uvx*), Read, Edit, Write, AskUserQuestion
---

You are running `/revisit` in the **current working directory's repo**.
Goal: create the three top-of-repo documentation/config files — `README.md` (with
the full standard rhiza badge set), `CLAUDE.md`, and `mkdocs.yml` — or, if they
already exist, **revisit** them: refresh the badges, fill gaps, and correct drift
**without discarding hand-written prose**. Adapt everything to whatever repo this
runs in by reading its git remote, `pyproject.toml`, workflow files, and `.rhiza/`
config at runtime.

Argument (optional): `$ARGUMENTS` — `readme`, `claude`, or `mkdocs` to touch only
that one file; `all` (or empty) for all three.

**Revisit, don't clobber.** For every file: if it already exists, treat existing
prose, tables, and section order as authoritative content to preserve. Only
*replace* the badge block, *add* missing standard sections, and *correct* stale
facts (wrong owner/repo, dead workflow name, changed template version). Never
delete a hand-written section to "standardize" it — surface it in the report
instead. Prefer `Edit` over `Write` when a file already exists so the diff stays
reviewable; use `Write` only to scaffold a file that doesn't exist yet.

Work through these steps. Stop and report if a precondition fails.

## 1. Detect repo identity and metadata

Gather the facts the badges and docs depend on — do not hardcode `jebel-quant/rhiza`:

- **Repo root & clean check.** `git rev-parse --show-toplevel`; note `git status --porcelain` (a dirty tree is fine here — you're editing docs — but report it so the user knows what they're mixing with).
- **Platform + owner/repo** from `git remote get-url origin`:
  - `github.com` → GitHub; `OWNER/REPO` from the URL.
  - `gitlab.com` or a self-hosted GitLab host → GitLab; `NAMESPACE/PROJECT` from the URL.
  - No remote → ask the user for `owner/repo` and platform, or scaffold with `OWNER`/`REPO` placeholders and flag them in the report.
- **Default branch:** `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name` (GitHub) / `glab repo view` (GitLab), fallback `main`.
- **Project type & metadata:**
  - Python/rhiza repo? `pyproject.toml` present → read `project.name`, `project.requires-python` / classifiers (→ Python versions), `project.license`, and whether it's published (`gh` release exists, or a PyPI name). Also check `.rhiza/template.yml` (`ref`/`template-branch` → template version).
  - Non-Python repo (e.g. this `claude-config` repo) → skip Python-specific badges; keep the platform, license, and CI badges that still apply.
- **CI workflow file(s):** `find .github/workflows -maxdepth 1 -name '*.yml'` (GitHub) or `.gitlab-ci.yml` (GitLab). The CI badge must point at a workflow file that actually exists — prefer one named like `*ci*` (rhiza ships `rhiza_ci.yml`); if none, omit the CI badge and note it.
- **License:** presence of a `LICENSE`/`LICENSE.md` file and its type (read the SPDX header or `pyproject` license). Omit the license badge if there is no license file.
- **Coverage service:** a `codecov.yml`/`.codecov.yml`, a Codecov step in CI, or a `coverage` badge already in the README → include the Codecov badge; else omit.

## 2. README.md — build the standard badge block

Assemble the badge block adapting the canonical rhiza set to **this** repo's
`OWNER/REPO`, platform, and detected metadata. Include a badge only when its
backing fact exists (step 1); **omit, don't fake**. Standard set, in this order:

- **Release / template version** — the repo's own release if it publishes one, e.g.
  `![GitHub Release](https://img.shields.io/github/v/release/OWNER/REPO?sort=semver)`.
  For a rhiza-managed repo also add a template-version badge derived from `.rhiza/template.yml`'s `ref`.
- **License** — `[![License: <SPDX>](https://img.shields.io/badge/License-<SPDX>-green.svg)](LICENSE)`.
- **Python versions** (Python repos only) — `[![Python versions](https://img.shields.io/badge/Python-<versions •-joined>-blue?logo=python)](https://www.python.org/)`.
- **CI** —
  - GitHub: `[![CI](https://github.com/OWNER/REPO/actions/workflows/<WORKFLOW>.yml/badge.svg?event=push)](https://github.com/OWNER/REPO/actions/workflows/<WORKFLOW>.yml)`
  - GitLab: `[![pipeline](https://gitlab.com/NS/PROJECT/badges/<BRANCH>/pipeline.svg)](https://gitlab.com/NS/PROJECT/-/pipelines)`
- **Coverage** (if a coverage service is detected) —
  - GitHub + Codecov: `[![codecov](https://codecov.io/gh/OWNER/REPO/branch/<BRANCH>/graph/badge.svg)](https://codecov.io/gh/OWNER/REPO)`
  - GitLab: `[![coverage](https://gitlab.com/NS/PROJECT/badges/<BRANCH>/coverage.svg)](https://gitlab.com/NS/PROJECT/-/commits/<BRANCH>)`
- **Code style: ruff** (Python repos) — `[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg?logo=ruff)](https://github.com/astral-sh/ruff)`.
- **uv** (Python repos using uv) — `[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)`.
- **CodeFactor** (GitHub) — `[![CodeFactor](https://www.codefactor.io/repository/github/OWNER/REPO/badge)](https://www.codefactor.io/repository/github/OWNER/REPO)`.
- **OpenSSF Scorecard** (public GitHub repos) — `[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/OWNER/REPO/badge)](https://scorecard.dev/viewer/?uri=github.com/OWNER/REPO)`.
- **Open in Codespaces** (GitHub) — `[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/OWNER/REPO)`.

Convention: put the release badge on its own line, then the rest as a block of
`[![…](…)](…)` links, matching upstream rhiza. When **revisiting**, replace the
existing top-of-file badge block wholesale with this freshly-computed one (badges
are generated, not hand-authored), but keep the `# Title` and everything below.

## 3. README.md — body

- **If the file doesn't exist**, scaffold: `# <project name>`, a one-line description, the badge block from step 2, then standard sections — **Installation/Setup**, **Usage**, **Development**, and **License**. In the Development section, don't hand-list the `make` targets: emit the marker line `` Run `make help` to see all available targets: `` followed by an empty fenced code block, then let step 4 fill it from live `make help` output. Keep it concise and truthful to what the repo actually contains — don't invent features.
- **If it exists**, revisit: refresh the badge block, then read the body and add only *missing* standard sections; leave existing prose intact. Fix obviously stale references (old repo name, renamed workflow). List substantive gaps you chose not to auto-fill in the report rather than guessing.

## 4. README.md — sync the `make help` target block

Keep the README's list of `make` targets in lockstep with the actual `Makefile`,
so contributors never read a stale target list. This reproduces the retired
rhiza-tools `update-readme` command: a marker line plus the fenced code block
right after it, refreshed from live `make help` output. Idempotent — re-running
against an unchanged `Makefile` produces no diff. (Runs as part of the README
work, i.e. when `$ARGUMENTS` is `readme` or `all`.)

- **Precondition — is there a `help` target?** Only do this if the repo has a
  `Makefile` (or `makefile`/`GNUmakefile`) exposing a `help` target
  (`grep -E '^help:' Makefile`, or a `.DEFAULT_GOAL := help` line). If there's no
  Makefile or no `help` target, **skip this step and note it in the report** — no-op.
- **Capture and clean the output.** Run `make help` and sanitize it, because the
  help target typically colorizes target names and recursive makes emit directory
  chatter:
  - strip ANSI color escape codes, and
  - drop any `make[N]: Entering directory …` / `make[N]: Leaving directory …` lines.

  e.g. `make help 2>/dev/null | sed -E $'s/\x1b\\[[0-9;]*m//g' | grep -vE '^make\[[0-9]+\]: (Entering|Leaving) directory'`.
- **Find the marker.** Look in `README.md` for the literal line
  `` Run `make help` to see all available targets: `` and the fenced ```` ``` ````
  code block immediately following it.
  - **Marker + following fence both present** → replace only the *contents* of
    that fenced block with the cleaned output; leave the marker line, the fence
    delimiters, and everything else byte-for-byte intact. Use `Edit` so the diff
    stays reviewable. This is the idempotent common case.
  - **Marker absent (or present with no following fence)** on an existing,
    hand-written README → this is a no-op for the sync itself, exactly as
    `update-readme` behaved: **skip and report**. The exception is when you are
    scaffolding a new README or adding a missing **Development** section in step 3
    — there you *do* emit the marker + a fenced block and populate it here, since
    filling in a missing standard section is squarely `/revisit`'s job.
- Don't reformat, sort, or annotate the captured lines — the block mirrors
  `make help` verbatim (post-cleanup) so the next run stays a no-op.

## 5. CLAUDE.md

`CLAUDE.md` is guidance for future Claude Code sessions in this repo — the
build/test commands, the architecture, and (for rhiza repos) the crucial
**locally-owned vs. Rhiza-owned** split that `quality` scoring
depends on.

- **If it doesn't exist**, scaffold with:
  - **Commands** — the canonical `make` targets (`make fmt`, `make typecheck`, `make docs-coverage`, `make deptry`, `make security`, `make validate`, `make test`, `make sync`) with a one-line purpose each; note the command-execution policy (prefer bare `make <target>`, never call `.venv/bin/...` directly).
  - **Architecture** — the `src/` layout and layering, gathered by actually reading the tree (don't invent). Skip or adapt for non-Python repos.
  - **Rhiza template split** — which files are synced from `jebel-quant/rhiza` (the `files:` block of `.rhiza/template.lock` if present) and are therefore fixed upstream, vs. the locally-owned `src/`, `tests/`, `pyproject.toml`, `README.md`, project docs. State the rule: gaps in Rhiza-managed files are fixed upstream, not here.
  - **Conventions** — anything non-obvious a new session must know (test layout, coverage threshold from `COVERAGE_FAIL_UNDER`, docstring expectations).
- **If it exists**, revisit: verify the `make` targets against the actual `Makefile`, verify the synced-files list against the current `.rhiza/template.lock`, and correct drift. Preserve hand-written guidance and any user-added instructions verbatim — only fix facts that are demonstrably wrong.
- **Never** put secrets, tokens, or machine-local paths in `CLAUDE.md`.

## 6. mkdocs.yml

The docs site config. In a rhiza `book`-profile repo, the top-level `mkdocs.yml`
is **locally-owned** (site metadata + `nav`) and inherits shared theme/plugins
from the Rhiza-synced `docs/mkdocs-base.yml` via `INHERIT:` — so this command
writes the local file and must **not** duplicate or edit the synced base.

- **Precondition — is a docs site even in scope?** Only manage `mkdocs.yml` if the repo builds docs with MkDocs: a `docs/` dir, a `make docs`/book target, `mkdocs`/`mkdocs-material` in deps, or an existing `mkdocs.yml`. If none of these, skip this step and say so (don't scaffold a docs site the repo doesn't have). If the repo uses a *different* docs generator, note that and skip rather than converting it.
- **If it doesn't exist** (but MkDocs is in scope), scaffold, mirroring the upstream rhiza shape and adapting to this repo:
  - `INHERIT: docs/mkdocs-base.yml` **only if that synced base file actually exists** in the repo; otherwise emit a self-contained config with `theme: {name: material}` and note that the base wasn't found.
  - `site_name` from `project.name`; `site_description` from `pyproject.toml`'s description; `site_url` as the platform Pages URL (`https://OWNER.github.io/REPO/` for GitHub Pages, or the GitLab Pages equivalent); `repo_url` / `repo_name` from step 1's owner/repo.
  - `docs_dir: docs`.
  - A `nav:` built from the Markdown files that actually exist under `docs/` (`find docs -name '*.md'`), grouped sensibly (Home first). Don't invent nav entries for files that aren't there.
- **If it exists**, revisit: correct `site_name`/`site_url`/`repo_url`/`repo_name` drift against step 1's detected identity, verify the `INHERIT:` target still exists, and reconcile `nav:` with the actual files under `docs/` — flag entries pointing at missing files and files not yet in the nav, but **don't** aggressively reorder a hand-curated nav. Preserve custom theme/plugin/extension overrides verbatim.
- Never edit the Rhiza-synced `docs/mkdocs-base.yml` here — drift there is fixed upstream via `make sync`.

## 7. Verify and report

- If badge URLs are cheap to sanity-check and `gh`/`glab` is authenticated, confirm the referenced CI workflow file exists (a badge to a non-existent workflow renders broken). Don't hard-fail on this — just flag broken ones.
- Do **not** commit, branch, or open a PR — this command only writes the files, leaving them staged in the working tree for the user to review. (Say so, and remind them to `git add`/commit when happy.)
- Report concisely: which files were created vs. revisited, the final badge list (and any omitted-because-not-detected), whether the `make help` target block was refreshed / added / skipped (and why, if skipped), stale facts corrected, and any hand-written gaps you deliberately left for the user to fill.
