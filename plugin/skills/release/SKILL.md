---
description: Prepare a release in any git repo that declares its version locations (no .rhiza/ needed) — choose a version from a table, bump, regenerate the changelog, and open a release PR. Tags the merged commit on a second run.
argument-hint: "[version e.g. v1.4.0]  (optional; omit to pick from a table of candidates)"
allowed-tools: Bash(git*), Bash(gh*), Bash(glab*), Bash(uv*), Bash(uvx*), Bash(make*), Bash(cat*), Bash(grep*), Read, Edit, AskUserQuestion
disable-model-invocation: true
---

You are running `/release` in the **current working directory's repo**. Goal: land the
version bump on the default branch **through a pull request**, like every other change,
and then tag the commit that actually merged.

**That splits the release into two phases, and the split is forced by squash-merge.** A
tag must point at a commit that exists on the branch you publish from; a squash-merge
replaces the branch's commits with a new one, so a tag cut before the merge names a SHA
that never lands. There is no ordering of one invocation that fixes this — the commit to
tag does not exist until the human merges. So:

| Phase | You run | It ends with |
| --- | --- | --- |
| **A — the release PR** | `/rhiza:release` on a clean default branch | a pushed branch and an open PR. **No tag.** |
| **B — the tag** | `/rhiza:release` again, after that PR merges | the merged commit tagged locally, push handed back |

Step 1 works out which phase it's in from the repo's own state; the user does not
declare it.

**Never push to the default branch, and never move an existing tag.** Phase A pushes
one *release branch* — the same thing `/rhiza:init` and `/rhiza:update` do, and the only
push either phase makes on its own. Pushing the **tag** stays a deliberate human action,
because that is what triggers the release workflow. If anything is ambiguous, stop and
report.

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
  default branch yet, **stop and say so** — that includes a release branch this command
  opened in phase A, which is not tagged until it merges. Both phases run from the
  default branch.
- **Version config.** `[tool.bumpversion]` must exist, in `.bumpversion.toml` or
  `pyproject.toml`:
  ```bash
  uvx bump-my-version show current_version
  ```
  If that fails, **stop** — the repo hasn't declared where its version lives, and
  guessing is exactly what this command refuses to do. Report what's needed: a
  `.bumpversion.toml` with `current_version` and one `[[tool.bumpversion.files]]` entry
  per location (see step 6 for the stub-pin case). Hold the value as `CURRENT`.
- **Unless the config is tag-derived, which is how Go *and Rust* declare it.** Both
  `go-core` and `rust-core` ship a `.bumpversion.toml` that deliberately omits
  `current_version`: the file is *synced*, so it must not carry a value only the consuming
  repo can own — the next `/rhiza:update` would reset it. Each therefore derives the
  current version from the newest matching tag, and on a repo that has not been tagged yet
  the command above fails with "Unable to determine the current version" — a **declared**
  version location with nothing to read yet, which is not the same fact as no config at
  all and must not be reported as one. Tell them apart:
```bash
grep -lq '^\[tool\.bumpversion\]' .bumpversion.toml pyproject.toml 2>/dev/null
```
  A config that exists and no tags → this is the repo's **first** release. Hold `CURRENT`
  as whatever that language's declared location actually carries, and pass it explicitly
  in step 6 — **`0.0.0` is right for Go only**, and passing it to a crate fails the bump:

  | language | `CURRENT` comes from | on a fresh repo |
  | --- | --- | --- |
  | Go | `const Version` in `internal/version/version.go` | `0.0.0` |
  | Rust | `version` under `[package]` in `Cargo.toml` | `0.1.0`, what `cargo init` writes |

  Read the value rather than assuming it:
```bash
grep -m1 '^const Version' internal/version/version.go 2>/dev/null
grep -m1 '^version = ' Cargo.toml 2>/dev/null
```
  `-m1` on a manifest cargo wrote finds `[package]`'s, since that table leads the file; if
  the manifest has been rearranged, `Read` it instead of trusting the first match. No
  config at all → stop, as above.
- **On the default branch.** Compare `git branch --show-current` against the remote
  default (`gh repo view --json defaultBranchRef`, else `git remote show origin`). If
  not, warn and ask (`AskUserQuestion`) — releasing off a side branch is unusual, not
  forbidden.
- **Up to date.** `git fetch --tags origin`, and `git pull --ff-only` so the merged
  release PR is actually in your history — phase B reads the version off it.

## 1a. Work out which phase you're in

The repo's own state says it, so don't ask:

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/check_version_bump.py" \
  --current "$CURRENT"
```

It prints `current` and `highest` (the highest existing tag) side by side. Compare them
**as semver**, which is what that script already did to pick the floor:

- **`CURRENT` == `highest`** — the declared version is released. This is **phase A**:
  continue to step 2.
- **`CURRENT` > `highest`** — a bump has landed on the default branch that no tag names.
  This is **phase B**: the release PR merged and only the tag is missing. Set
  `TARGET=v$CURRENT`, skip steps 2–9 entirely, and go to **step 10**. Say which phase
  you picked and why, so the user can correct you if a hand-edit put the repo here.
- **`CURRENT` < `highest`** — a reverted bump, or a tag cut ahead of the config. Neither
  phase fits; **stop and report both values.** The floor in step 4 already accounts for
  this, but arriving here means something rewrote history and guessing is not this
  command's job.

**Phase B is what makes the flow resumable, and it is not a special case** — it is the
normal second half of every release. The user merges the PR whenever review finishes,
which may be days later and in a different session; the only state that carries across
is what is committed to the default branch, which is exactly what the comparison above
reads.

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

**On a tag-derived config (Go or Rust), add `--current-version "$CURRENT"`.** With no
`current_version` key and no tag to derive one from, the bump fails exactly as step 1's
`show` did — and with a value that disagrees with the declared location, it fails
differently and more confusingly: `Did not find 'const Version = …'` on Go, and on Rust
`Did not find '(?ms)^\[package\]…version = "…"' in file: 'Cargo.toml'`. That second
message is precisely what a hardcoded `CURRENT=0.0.0` produces against a crate `cargo
init` started at `0.1.0`, which is why step 1 *reads* the value instead of assuming one.
Passing what step 1 settled makes every case deterministic.

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

## 8. Commit the bump on a release branch

**Read `prompts/pr-base.md` and follow it**, with `BRANCH_PREFIX=rhiza_release_${TARGET}`.
It returns `$BRANCH` — based on an up-to-date `origin/$DEFAULT` — and `$DEFAULT`. That
procedure is where the *"the default branch is never pushed to"* rule lives, and
`/rhiza:init` and `/rhiza:update` follow the same one, so a release branch is shaped
like every other change this plugin proposes.

**One wrinkle this caller has to handle:** steps 6 and 7 already wrote to the working
tree, on the default branch. `git checkout -b` carries those uncommitted changes onto
the new branch, which is what you want — but only if the branch is created *from the
commit you bumped against*. `pr-base` bases it on `origin/$DEFAULT`, which step 1 already
fast-forwarded to, so they are the same commit. If `git checkout -b` reports it cannot
switch because of local changes, **stop** — that means `origin/$DEFAULT` moved under you
mid-run, and the bump was computed against history that is no longer the base.

```bash
git add --all
git commit -m "chore: release $TARGET"
```
`git add --all` is safe here *because the tree was verified clean in step 1* — the only
changes present are the ones steps 6 and 7 made.

**Do not tag.** The tag belongs on the merged commit, which does not exist yet; step 10
creates it. Creating one here is the exact mistake the two-phase split exists to prevent
— a squash-merge would strand it on a SHA that never reaches the default branch.

```bash
git push --set-upstream origin "$BRANCH"
```

## 9. Open the release PR — then stop

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/platform_cli.py" \
  pr-create --base "$DEFAULT" --head "$BRANCH" \
  --title "chore: release $TARGET" --body-file <BODY>
```
It detects the platform from `origin` and issues `gh pr create` or `glab mr create`,
which differ in subcommand *and* flag names — don't hand-write either form. Exit **1**
means the CLI is missing or failed: not fatal, because the branch is already pushed, so
relay the note and print the compare URL.

Body: `CURRENT` → `TARGET`, every file the bump touched, the changelog section being
added, and — the part a reviewer cannot see from the diff — that **merging this PR does
not publish the release**, because the tag is cut afterwards from the merged commit by a
second `/rhiza:release` run.

Then **stop.** Merging is the human's call and the checks have to run. Tell them to
re-run `/rhiza:release` once it lands.

> **A repo that pins its own tag cannot use this flow, and it is the one exception.**
> When CI stubs delegate via `uses: <owner>/<repo>/…@vX.Y.Z` and the repo being released
> *is* that repo (the step-6 stub-pin case), the release PR references a tag that does
> not exist yet. A cross-repo `uses:` resolves at `Set up job`, before checkout, so every
> job dies before running anything:
> ```
> ##[error]Unable to resolve action `owner/repo@vX.Y.Z`, unable to find version `vX.Y.Z`
> ```
> Required checks can therefore *never* go green, and the PR is unmergeable except by
> bypassing branch protection. Detect it before opening the PR — a self-referencing
> `uses:` in `.github/` that step 6 bumped — and if it's there, **say so and ask**
> (`AskUserQuestion`) rather than opening a PR that cannot merge. Two honest options:
> commit and tag on the default branch directly, pushing both refs at once with
> `git push --atomic origin HEAD "$TARGET"`
> — which needs a protection bypass and is why `--atomic` matters (two sequential pushes
> leave a window where the branch is published and the tag is not, and every run started
> in it fails as above); or fix the cause first, which is the durable answer: a repo
> consuming its **own** action or reusable workflow should reference it by local path
> (`uses: ./.github/actions/<name>`), which needs no tag, cannot drift, and makes the
> repo releasable by PR like any other.

## 10. Phase B — tag the merged commit

You are here because step 1a found `CURRENT` > the highest tag. The release PR has
merged; `TARGET` is `v$CURRENT`.

**Verify you are tagging the right commit before creating anything:**

```bash
git rev-parse --abbrev-ref HEAD
git status --porcelain
git log -1 --format='%H %s'
```
On `$DEFAULT`, clean, and up to date with `origin/$DEFAULT` after step 1's `pull
--ff-only`. If `HEAD` is behind the remote, stop — you would tag a commit that isn't the
merge.

**Confirm the merged tree really carries `TARGET`.** The version the config declares is
what step 1a read, so this is a check that the *merge* preserved it, not a re-read:

```bash
uvx bump-my-version show current_version
```
It must equal `${TARGET#v}`. A mismatch means the PR was edited before merging — stop
and report both values.

Then guard and tag:

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/check_version_bump.py" \
  "$TARGET" --current "$CURRENT"
git tag -a "$TARGET" -m "release $TARGET"
```
The guard runs **again**, on the merged history: it is cheap, and between phases the repo
gained commits and possibly tags, so the fact that `TARGET` was legal in phase A is no
longer evidence that it is legal now. Non-zero exit means stop. **Never** `-f`.

Then hand the push over — this is the deliberate human action that triggers release CI:

```bash
git push origin "$TARGET"
```
Only the tag: the commit is already on the default branch, put there by the merge.

## 11. Report

**In phase A**, concisely: `CURRENT` → `TARGET`, with confirmation that it strictly
increases past every prior release; every file the bump touched (manifests,
`pyproject.toml`, any stub pins, the bumpversion config); the changelog diff summary; the
branch and the PR/MR URL. State plainly that **no tag exists yet** and the release is not
public — merging the PR does not publish it — and that the next step is to re-run
`/rhiza:release` after the merge, which will tag the merged commit.

**In phase B**: the tag, the commit SHA it points at, confirmation that the merged tree
declares `TARGET`, and the single `git push origin <TARGET>`. State that **nothing has
been pushed** and the release isn't public until the tag is. To undo: `git tag -d
<TARGET>` — and note that unlike the old single-phase flow there is no commit to reset,
because the bump landed by merge.

If the repo has no release workflow, publish manually with the bundled mapper, which
picks `gh` or `glab` from `origin`:
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/platform_cli.py" \
  release-create --tag <TARGET> --notes-file <NOTES>
```
On GitHub, omitting `--notes-file` falls back to `gh release create --generate-notes`.
**On GitLab it is required** — `glab` has no `--generate-notes`, so the mapper refuses
rather than publishing a release with empty notes. Step 5 already rendered the notes
with `git-cliff`; write them to a file and pass that.
