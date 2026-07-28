---
description: Prepare a release locally for any git repo that declares its version locations (no .rhiza/ required, unlike /quality) — derive the next semantic version from the conventional commits via git-cliff, guard that it strictly increases past every previous release, then let bump-my-version write it into every location the repo declares (pyproject.toml, plugin manifests, self-referencing CI stub pins), regenerate CHANGELOG.md, and commit + tag. The version locations live in the repo's own [tool.bumpversion] config, so nothing is inferred and a dependency that happens to share the version number is never rewritten. Stops before pushing: it prints the push commands, and pushing the tag is what triggers the release CI. Never pushes or force-tags.
argument-hint: "[version e.g. v1.4.0]  (optional; defaults to the git-cliff-derived bump)"
allowed-tools: Bash(git*), Bash(uv*), Bash(uvx*), Bash(make*), Bash(cat*), Bash(grep*), Read, Edit, AskUserQuestion
---

You are running `/release` in the **current working directory's repo**. Goal: prepare a
clean, reviewable release **locally** — bump every declared version location,
regenerate the changelog, commit, and tag — then **stop and hand the push back to the
user**. Pushing the tag triggers the release workflow, so that stays a deliberate human
action.

**Never push, and never move an existing tag.** This command writes to the working tree
and creates one local commit plus one tag. If anything is ambiguous, stop and report.

**The repo declares where its version lives; you don't guess.** `bump-my-version` reads
`[tool.bumpversion]` (in `.bumpversion.toml` or `pyproject.toml`) and rewrites only the
explicit search/replace patterns listed there. That is what makes it safe to bump a
`pyproject.toml` version, a plugin manifest and a CI stub pin in one step **without**
touching a dependency that happens to share the current version number. Never
hand-edit a version to "help" — if a location is missing, the fix is a config entry.

Argument (optional): `$ARGUMENTS` — an explicit version like `v1.4.0`, which skips the
menu. Anything that isn't semver-shaped is **not** a target: note it and offer the menu
anyway (step 3).

## 1. Preconditions

- **A git repo with tags reachable.** That's the only structural requirement. `/release`
  deliberately does **not** check for `.rhiza/` — nothing in this flow comes from the
  template: the version locations are repo-owned config, `git-cliff` reads conventional
  commits, and tags are tags. (Contrast `/quality`, where every gate *is* a synced `make`
  target, so its rhiza-managed check is load-bearing.) This is what lets `/release`
  release the plugin repo itself as well as a managed application.
- **Clean tree.** `git status --porcelain`; if dirty, stop and show the files. A release
  is cut from committed work.
- **Releasing what will actually ship.** The tag must point at a commit that exists on
  the branch you publish from. If `HEAD` is a feature branch whose commits aren't on the
  default branch yet, **stop and say so**: a squash-merge rewrites those SHAs, so the tag
  would end up on a commit that never lands. Merge first, then release from the default
  branch.
- **Version config.** `[tool.bumpversion]` must exist, in `.bumpversion.toml` or
  `pyproject.toml`:
  ```bash
  uvx bump-my-version show current_version
  ```
  If that fails, **stop** — the repo hasn't declared where its version lives, and
  guessing is exactly what this command refuses to do. Report what's needed: a
  `.bumpversion.toml` with `current_version` and one `[[tool.bumpversion.files]]` entry
  per location (see step 6 for the stub-pin case). Hold the value as `CURRENT`.
- **On the default branch.** Compare `git branch --show-current` against the remote
  default (`gh repo view --json defaultBranchRef`, else `git remote show origin`). If
  not, warn and ask (`AskUserQuestion`) — releasing off a side branch is unusual, not
  forbidden.
- **Up to date.** `git fetch --tags origin`, so the tag guard sees real history.

## 2. Gather the candidate versions

Two independent inputs, both needed for the menu in step 3.

**What the commits imply** — `uvx git-cliff --bumped-version` (`feat` → minor, `fix` →
patch, a `!` or `BREAKING CHANGE` footer → major). Hold as `DERIVED`. Note git-cliff
applies **no pre-1.0 special case**: a breaking change at `0.x` derives `v1.0.0`, which
spends the 1.0 signal whether or not the project is ready for it.

**What each bump kind would be** — computed from the floor, so every option is
guaranteed to be legal:
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/check_version_bump.py" \
  --current "$CURRENT"
```
With no target it prints the floor and the `patch`/`minor`/`major` candidates and exits 0.

If `$ARGUMENTS` is a `vX.Y.Z` version, that's an explicit choice — skip the menu, set
`TARGET`, and go straight to the guard in step 4. **`$ARGUMENTS` that isn't a version**
(a note, a phrase like "for client repos") is not a target — say you're treating it as a
comment and continue to the menu.

## 3. Choose the target from a menu

**Never tag without this.** Present the candidates with `AskUserQuestion` — a list, not
a single value with an invitation to override, because the right bump is a judgement the
deriver cannot make. Put the **git-cliff-derived one first, marked "(Recommended)"**,
and label each with what it means:

- `$DERIVED` — *what the commits imply*: name the types that drove it (e.g. "2 breaking
  changes, 5 feat").
- the `major` / `minor` / `patch` candidates from step 2 that differ from `$DERIVED`,
  each with its consequence — a major "signals a breaking API"; a minor "adds features,
  compatible"; a patch "fixes only".
- **When the repo is pre-1.0 and `$DERIVED` is `v1.0.0`**, say so explicitly in that
  option's description and make sure the `minor` candidate is also offered: at `0.x` a
  breaking change does not *require* 1.0, and going there is a deliberate statement of
  API stability.

Show `CURRENT` and the floor alongside, so the user can see what each option is
relative to. The user may also supply their own value.

**Step 4 then guards whatever comes back**, including a hand-typed value — the menu
offers only legal candidates, but a custom answer hasn't been checked.

## 4. Guard that it strictly increases

**This is the step that prevents the only unrecoverable mistake here** — a pushed tag is
effectively permanent. `bump-my-version` will happily accept a backwards version and
knows nothing about tags, so the check is explicit (**keep the quotes**; in a source
checkout fall back to the repo-relative path):

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/check_version_bump.py" \
  "$TARGET" --current "$CURRENT"
```

It compares as **semver, not strings** (so `v1.10.0` beats `v1.9.0`), takes the floor as
the greater of `CURRENT` and the highest existing tag — a repo can carry a version
*below* its newest tag after a reverted bump — and refuses a tag that already exists.
Exit **1** means stop; exit **2** means the version is malformed. Do not proceed past a
non-zero exit, and never pass `--force` to anything to get around it.

## 5. Preview the release notes

```bash
uvx git-cliff --unreleased --tag "$TARGET"
```
Empty output means no unreleased commits — stop and report; there's nothing to release.

## 6. Write the version everywhere it's declared

```bash
uvx bump-my-version bump --new-version "${TARGET#v}" --no-commit --no-tag
```
`--no-commit --no-tag` because step 7 regenerates the changelog *before* committing, so
the release commit contains the version bump and the changelog together. This updates
every `[[tool.bumpversion.files]]` entry plus `current_version` in the config itself.

Then **show `git diff --stat`** so the user sees exactly which files moved.

> **Anchor the `pyproject.toml` pattern.** `search`/`replace` are applied to **every**
> occurrence in the file, so the obvious `search = 'version = "{current_version}"'`
> also rewrites a `[tool.something].version` that happens to share the number. Anchor
> it to the `[project]` table:
> ```toml
> [[tool.bumpversion.files]]
> filename = "pyproject.toml"
> regex = true
> search = '(?ms)^\[project\]((?:(?!^\[)[\s\S])*?)^version = "{current_version}"'
> replace = '[project]\1version = "{new_version}"'
> ```
> Dependency pins (`httpx>=1.2.0`, `rich==1.2.0`) are never at risk either way — they
> aren't line-anchored `version = ` assignments — but a second `[tool.*]` table is.
> If the repo's config uses the naive form, **say so** rather than silently bumping.

> **Self-referencing CI stubs.** Rhiza distributes CI as thin stubs that delegate via
> `uses: <owner>/<repo>/.github/…@vX.Y.Z`. When the repo being released *is* the one
> those stubs point at, the pin must move with the release — otherwise the published
> tag ships workflows calling the **previous** version's reusable workflows. That's a
> config entry, not something to hand-edit:
> ```toml
> [[tool.bumpversion.files]]
> filename = ".github/workflows/rhiza_ci.yml"
> search = "OWNER/REPO/.github/workflows/reusable.yml@v{current_version}"
> replace = "OWNER/REPO/.github/workflows/reusable.yml@v{new_version}"
> ```
> If you can see such a self-reference in `.github/` that the config does **not** cover,
> stop and say so — that's a config gap, and bumping past it publishes stale stubs.
> Third-party pins (`actions/checkout@v5`) and floating refs (`@main`) are never
> rewritten.

## 7. Regenerate the changelog

```bash
uvx git-cliff --tag "$TARGET" --output CHANGELOG.md
```
This folds the unreleased commits under the new tag. Prefer this explicit form over
`make changelog`, which usually omits `--tag` and so leaves the new section unlabelled.
Show a short diff summary.

## 8. Commit and tag locally

```bash
git add --all
git commit -m "chore: release $TARGET"
git tag "$TARGET"
```
`git add --all` is safe here *because the tree was verified clean in step 1* — the only
changes present are the ones steps 6 and 7 made. An annotated tag is fine
(`git tag -a "$TARGET" -m "release $TARGET"`); **never** `-f`.

## 9. Stop — hand the push to the user

```bash
git push origin HEAD      # the release commit
git push origin <TARGET>  # the tag — triggers the release workflow
```
Explain that pushing the **tag** is what triggers release CI. If the repo has no such
workflow, `gh release create <TARGET> --generate-notes` (or `glab release create`) does
it manually.

## 10. Report

Concisely: `CURRENT` → `TARGET` with the derivation rationale and confirmation that it
strictly increases past every prior release; every file the bump touched (manifests,
`pyproject.toml`, any stub pins, the bumpversion config); the changelog diff summary;
the commit SHA and the tag; and the two push commands. State plainly that **nothing has
been pushed** and the release isn't public until the tag is. If they want to undo:
`git tag -d <TARGET>` and `git reset --hard HEAD~1`.
