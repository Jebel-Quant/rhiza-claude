---
description: Prepare a release in any git repo that declares its version locations (no .rhiza/ needed) — choose a version from a table, bump, regenerate the changelog, commit and tag. Stops before pushing.
argument-hint: "[version e.g. v1.4.0]  (optional; omit to pick from a table of candidates)"
allowed-tools: Bash(git*), Bash(uv*), Bash(uvx*), Bash(make*), Bash(cat*), Bash(grep*), Read, Edit, AskUserQuestion
disable-model-invocation: true
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
- **Unless the config is tag-derived, which is how Go declares it.** `go-core` ships a
  `.bumpversion.toml` that deliberately omits `current_version`, because a Go module's
  version *is* its git tag. On a repo that has not been tagged yet the command above
  therefore fails with "Unable to determine the current version" — a **declared** version
  location with nothing to read yet, which is not the same fact as no config at all and
  must not be reported as one. Tell them apart:
```bash
grep -lq '^\[tool\.bumpversion\]' .bumpversion.toml pyproject.toml 2>/dev/null
```
  A config that exists and no tags → this is the repo's **first** release: hold
  `CURRENT=0.0.0` (what `internal/version/version.go` ships) and pass it explicitly in
  step 6. No config → stop, as above.
- **On the default branch.** Compare `git branch --show-current` against the remote
  default (`gh repo view --json defaultBranchRef`, else `git remote show origin`). If
  not, warn and ask (`AskUserQuestion`) — releasing off a side branch is unusual, not
  forbidden.
- **Up to date.** `git fetch --tags origin`, so the tag guard sees real history.

## 2. Gather the candidate versions

Two independent inputs, both needed for the table in step 3.

**What each bump kind would be** — computed from the floor, so every option is
guaranteed to be legal:
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/check_version_bump.py" \
  --current "$CURRENT"
```
With no target it prints the floor and the `patch`/`minor`/`major` candidates and exits 0.

**What the commits contain** — read them, so the table can say which commit types point
at each row: `git log "$(git describe --tags --abbrev=0)"..HEAD --oneline`. Count the
`feat`, `fix`, and breaking (`!` / `BREAKING CHANGE`) commits. This is **evidence for the
table, not a recommendation** — `uvx git-cliff --bumped-version` would collapse the same
commits into a single answer, and that answer is exactly what this command declines to
put its thumb on. Do not run it, and do not name one row as the derived or expected one.

If `$ARGUMENTS` is a `vX.Y.Z` version, that's an explicit choice — skip the table, set
`TARGET`, and go straight to the guard in step 4. **`$ARGUMENTS` that isn't a version**
(a note, a phrase like "for client repos") is not a target — say you're treating it as a
comment and continue to the table.

## 3. Present the options as a table and let the user choose

**Never tag without this.** The right bump is a judgement you cannot make: it depends on
API-stability intent that the commit log does not record. So **lay out the options and
stop** — no recommended row, no default, no ordering that implies one, no "the commits
suggest X". Print a table, always in ascending version order:

```
current v0.6.0 · floor v0.6.0 (highest tag v0.6.0) · 7 unreleased commits

| Bump  | Version | Means                          | Commits pointing here      |
|-------|---------|--------------------------------|----------------------------|
| patch | v0.6.1  | fixes only, no new behaviour   | 2 fix                      |
| minor | v0.7.0  | adds features, compatible      | 4 feat, 2 fix              |
| major | v1.0.0  | signals a breaking API, and at | 1 breaking (`feat!:` sync) |
|       |         | 0.x also declares 1.0 stability|                            |
```

Rules for the table:

- **Every legal candidate gets a row** — `patch`, `minor`, `major` from step 2, ascending.
- The "Commits pointing here" column is a **count of what's in the log**, stated flatly.
  A row with no commits behind it still appears, with an empty cell.
- **When the repo is pre-1.0**, the `major` row must spell out that going to `v1.0.0` is a
  deliberate statement of API stability which `0.x` does not require — a breaking change
  at `0.x` is a legitimate `minor`. State it as a fact about both rows, not as a nudge
  toward either.
- Show `CURRENT`, the floor, and the highest existing tag above the table, so each option
  is visible relative to what already shipped.

Then collect the choice with `AskUserQuestion`, options in the **same ascending order as
the table** and none marked "(Recommended)". The user may also supply their own value.

**Step 4 then guards whatever comes back**, including a hand-typed value — the table
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

**On a tag-derived config (Go), add `--current-version "$CURRENT"`.** With no
`current_version` key and no tag to derive one from, the bump fails exactly as step 1's
`show` did — and with a tag that disagrees with `internal/version/version.go`, it fails
differently and more confusingly ("Did not find 'const Version = …'"). Passing the value
step 1 settled makes both cases deterministic.

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

## 7. Add the new section to the changelog

**Prepend; never regenerate.** This is step 5's preview command with `--prepend`, so
what you showed the user is exactly what lands:

```bash
uvx git-cliff --unreleased --tag "$TARGET" --prepend CHANGELOG.md
```
`--unreleased` scopes the run to commits after the last tag, `--tag` labels them, and
`--prepend` inserts that one section above the existing content without touching a byte
of it. Prefer it over `make changelog`, which usually omits `--tag` and so leaves the new
section unlabelled.

**Then diff the file and check that the only change is the new section.** Not a
formality — it's how you catch the two ways this step goes wrong:

- **`--output` rewrites history that `--prepend` preserves.** The older form
  (`git-cliff --tag "$TARGET" --output CHANGELOG.md`) regenerates the *whole* file from
  commits reachable from `HEAD`. A tag that is no longer reachable — the normal outcome
  of a squash-merge, a rebase, or a branch deleted after release — is invisible to that
  walk, so its section is **deleted** and its commits are silently re-filed under the
  next reachable release. The diff shows edits to years-old sections, and the released
  changelog no longer matches what shipped. Releasing `rhiza-hooks` v1.1.0 hit exactly
  this: `## [0.7.0]` vanished and its two commits moved into `0.7.1`.
- **`--prepend` is not idempotent.** Running it twice inserts the section twice. If you
  need to redo the step, `git checkout CHANGELOG.md` first — the tree was clean at step
  1, so that reset is safe and loses nothing.

If the diff shows anything beyond the new section, **stop and report** rather than
committing it.

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
git push --atomic origin HEAD <TARGET>  # commit + tag in one push
```
Explain that pushing the **tag** is what triggers release CI.

> **Push both refs in one command.** Two sequential pushes open a window in which the
> branch is published but the tag is not, and any repo whose workflows reference **their
> own** tag (`uses: <owner>/<repo>/…@vX.Y.Z`, the stub-pin case from step 6) fails every
> run started in it — a cross-repo `uses:` resolves at `Set up job`, before checkout, so
> the job dies before running anything:
> ```
> ##[error]Unable to resolve action `owner/repo@vX.Y.Z`, unable to find version `vX.Y.Z`
> ```
> `--atomic` lands both refs together, so the tag exists before any workflow is queued.
> If a push must be split, push the **tag first** — the branch can wait, the tag cannot.
> Check whether the repo's release workflow requires the tagged commit to be reachable
> from the default branch before relying on tag-first; most only validate tag format and
> that the version is newer than the latest release, which tag-first satisfies.
>
> The durable fix is on the repo side, not here: a repo consuming its **own** action or
> reusable workflow should reference it by local path (`uses: ./.github/actions/<name>`),
> which needs no tag and cannot drift. Suggest that if you see a self-pin, because the
> pinned form also makes a release PR unmergeable — its checks reference a tag that does
> not exist yet, so required checks can never pass and the release can only land by
> bypassing branch protection. If the repo has no such
workflow, publish it manually with the bundled mapper — which picks `gh` or `glab` from
`origin`:
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/platform_cli.py" \
  release-create --tag <TARGET> --notes-file <NOTES>
```
On GitHub, omitting `--notes-file` falls back to `gh release create --generate-notes`.
**On GitLab it is required** — `glab` has no `--generate-notes`, so the mapper refuses
rather than publishing a release with empty notes. Step 4 already rendered the notes
with `git-cliff`; write them to a file and pass that.

## 10. Report

Concisely: `CURRENT` → `TARGET` — the version the user picked, with confirmation that it
strictly increases past every prior release; every file the bump touched (manifests,
`pyproject.toml`, any stub pins, the bumpversion config); the changelog diff summary;
the commit SHA and the tag; and the two push commands. State plainly that **nothing has
been pushed** and the release isn't public until the tag is. If they want to undo:
`git tag -d <TARGET>` and `git reset --hard HEAD~1`.
