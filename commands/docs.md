---
description: Create or refresh the current repo's three top-of-repo documentation files — README.md (with the standard rhiza badge set, rendered by scripts/render_badges.py), CLAUDE.md (guidance for future Claude Code sessions), and mkdocs.yml (the locally-owned docs site config) — auto-detecting platform, owner/repo, and project metadata from the git remote, pyproject.toml, workflows, and .rhiza/ config. Preserves hand-written prose — it replaces the generated badge block, adds missing standard sections, and corrects stale facts, but never deletes what a human wrote. Also syncs the README's `make help` target list via scripts/sync_readme_help.py. Writes files only — no commit, no branch, no PR.
argument-hint: "[readme | claude | mkdocs | all]  (optional; defaults to all)"
allowed-tools: Bash(git*), Bash(gh*), Bash(glab*), Bash(grep*), Bash(find*), Bash(cat*), Bash(head*), Bash(make*), Bash(uv*), Read, Edit, Write, AskUserQuestion
---

You are running `/docs` in the **current working directory's repo**. Goal: author the
three top-of-repo documentation files — `README.md`, `CLAUDE.md`, `mkdocs.yml` — or,
where they exist, refresh them in place.

Argument (optional): `$ARGUMENTS` — `readme`, `claude`, or `mkdocs` for just that
file; `all` (or empty) for all three.

**Refresh, don't clobber.** Existing prose, tables, and section order are
authoritative. You may only: *replace* the generated badge block, *add* missing
standard sections, and *correct* stale facts (wrong owner/repo, dead workflow name,
changed template version). Never delete a hand-written section to standardise it —
report it instead. Prefer `Edit` over `Write` on an existing file so the diff stays
reviewable; `Write` is for scaffolding a file that isn't there.

**Detect, never hardcode.** Every fact comes from this repo at runtime. Nothing about
`jebel-quant/rhiza` is assumed.

## 1. Detect the repo's facts

- **Root + cleanliness** — `git rev-parse --show-toplevel`, and note
  `git status --porcelain`. A dirty tree is fine (you're editing docs) but say what
  the user is mixing your changes with.
- **Platform + `OWNER`/`REPO`** from `git remote get-url origin`: `github.com` →
  GitHub; a GitLab host → GitLab. No remote ⇒ ask, or scaffold with
  `OWNER`/`REPO` placeholders and flag them.
- **Default branch + visibility** — one call, both platforms:
  ```bash
  uv run --python 3.12 --no-project python \
    "${CLAUDE_PLUGIN_ROOT}/scripts/platform_cli.py" repo-view --json
  ```
  It returns `default_branch` and `visibility` **normalised**, which matters: `gh`
  answers `PUBLIC` and `glab` answers `public`, so comparing the raw value gives a
  platform-dependent answer. Exit 1 (no CLI, or logged out) ⇒ fall back to `main` and
  treat visibility as unknown.
- **Project metadata** — from `pyproject.toml` if present: `project.name`,
  `description`, `requires-python`/classifiers (→ Python versions), `license`. From
  `.rhiza/template.yml`: the template `ref`. Non-Python repo ⇒ skip the
  Python-specific facts.
- **CI workflow** — `find .github/workflows -maxdepth 1 -name '*.yml'`, preferring one
  named `*ci*` (rhiza ships `rhiza_ci.yml`); or `.gitlab-ci.yml`. A badge must point at
  a workflow that exists.
- **License** — a `LICENSE`/`LICENSE.md` file and its SPDX id.
- **Coverage service** — a `codecov.yml`/`.codecov.yml`, a Codecov step in CI, or an
  existing coverage badge.
- **ruff/uv usage** — `ruff.toml` or a `[tool.ruff]` table; a `uv.lock` or `uv_build`
  backend. (Visibility comes from the `repo-view` call above, which — unlike the bare
  `gh repo view --json visibility` this used to name — also answers on GitLab.)

## 2. README.md — the badge block

Badges are **generated, not hand-authored**, so don't write the URLs yourself — pass
the step-1 facts to the bundled renderer (**keep the quotes**; in a source checkout
`${CLAUDE_PLUGIN_ROOT}` is empty, so use the repo-relative path):
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/render_badges.py" \
  --owner "$OWNER" --repo "$REPO" --host <github|gitlab> --branch "$BRANCH" \
  [--license MIT] [--python-versions 3.12,3.13] [--ci-workflow rhiza_ci.yml] \
  [--template-ref v1.1.3] [--coverage codecov|gitlab] \
  [--uses-ruff] [--uses-uv] [--public] [--codespaces]
```
**Pass a flag only when step 1 actually found the fact.** The script enforces *omit,
don't fake* — every badge it skips comes back as an `omitted …` line with the reason,
which goes in your report. It emits the release badge on its own line, then the rest
as a block, matching upstream rhiza.

On an existing README, replace the top-of-file badge block **wholesale** with this
output — badges are generated — while keeping the `# Title` and everything below.

## 3. README.md — body

- **Missing** ⇒ scaffold: `# <project name>`, a one-line description, the badge block,
  then **Installation/Setup**, **Usage**, **Development**, **License**. In Development,
  don't hand-list `make` targets — emit the marker line
  `` Run `make help` to see all available targets: `` followed by an empty fenced code
  block, and let step 4 fill it. Keep it truthful to what the repo contains; invent no
  features.
- **Exists** ⇒ add only *missing* standard sections and fix demonstrably stale
  references. Substantive gaps you chose not to fill go in the report, not into
  guessed prose.

## 4. README.md — sync the `make help` block

Runs when `$ARGUMENTS` is `readme` or `all`:
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/sync_readme_help.py" .
```
It finds the marker and the fence after it, replaces **only that block's contents**
with sanitised live `make help` output, and is idempotent. It reports one of
`refreshed` / `unchanged` / `skipped` (no Makefile, no `help` target, no marker) —
relay that. Exit **2** means `make help` itself failed; report it and move on rather
than editing the README by hand. **Never** hand-edit this block: the script's
byte-level contract is what keeps re-runs a no-op.

## 5. CLAUDE.md

Guidance for future Claude Code sessions here — build commands, architecture, and (for
rhiza repos) the **locally-owned vs. Rhiza-owned** split that `/quality`'s scoring
depends on.

- **Missing** ⇒ scaffold with: **Commands** (the canonical `make` targets — `fmt`,
  `typecheck`, `docs-coverage`, `deptry`, `security`, `validate`, `test`, `sync` — one
  line each, plus the policy: prefer bare `make <target>`, never call `.venv/bin/…`);
  **Architecture** (the `src/` layout, read from the actual tree — don't invent);
  **Rhiza template split** (the `files:` block of `.rhiza/template.lock` is fixed
  upstream; `src/`, `tests/`, `pyproject.toml`, `README.md` are local — state the rule
  that gaps in Rhiza-managed files are fixed upstream, not here); **Conventions**
  (test layout, `COVERAGE_FAIL_UNDER`, docstring expectations).
- **Exists** ⇒ verify the `make` targets against the real `Makefile` and the synced
  list against the current `.rhiza/template.lock`, and correct drift. Preserve
  hand-written guidance verbatim.
- **Never** put secrets, tokens, or machine-local paths in it.

## 6. mkdocs.yml

In a rhiza `book`-profile repo the top-level `mkdocs.yml` is **locally owned** (site
metadata + `nav`) and inherits theme/plugins from the synced `docs/mkdocs-base.yml`
via `INHERIT:`. **Never edit that synced base** — drift there is fixed upstream.

- **In scope?** Only manage this file if the repo builds docs with MkDocs: a `docs/`
  dir, a `make docs`/book target, `mkdocs` in deps, or an existing `mkdocs.yml`. If
  not, skip and say so — don't scaffold a docs site the repo doesn't have. A different
  docs generator ⇒ note it and skip; don't convert it.
- **Missing** ⇒ scaffold: `INHERIT: docs/mkdocs-base.yml` **only if that file
  exists** (else a self-contained `theme: {name: material}`, noted); `site_name` and
  `site_description` from `pyproject.toml`; `site_url` as the Pages URL;
  `repo_url`/`repo_name` from step 1; `docs_dir: docs`; and a `nav:` built from the
  Markdown that actually exists under `docs/` (Home first). No nav entries for absent
  files.
- **Exists** ⇒ correct `site_name`/`site_url`/`repo_url`/`repo_name` drift, verify the
  `INHERIT:` target exists, and reconcile `nav:` against the real files — flag entries
  pointing at missing files and files not yet in the nav, but **don't** reorder a
  hand-curated nav. Preserve custom theme/plugin overrides verbatim.

## 7. Report

- If `gh`/`glab` is authenticated, confirm the badge's CI workflow file exists — a
  badge to a missing workflow renders broken. Flag it; don't hard-fail.
- **Nothing is committed.** No branch, no PR — the files are left in the working tree
  for review. Say so, and remind the user to `git add` when happy.
- Report: which files were created vs. refreshed, the final badge list plus every
  `omitted` reason from step 2, the step-4 outcome (`refreshed`/`unchanged`/`skipped`
  and why), stale facts corrected, and any hand-written gap you deliberately left.
