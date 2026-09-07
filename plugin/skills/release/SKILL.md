---
description: Release any git repo that declares its version locations (no .rhiza/ needed) in one run — choose a version from a table, bump, regenerate the changelog, open a release PR, let the forge merge it once its checks pass, then tag the merged commit.
argument-hint: "[version e.g. v1.4.0]  (optional; omit to pick from a table of candidates)"
allowed-tools: Bash(git*), Bash(gh*), Bash(glab*), Bash(uv*), Bash(uvx*), Bash(make*), Bash(cat*), Bash(grep*), Read, Edit, AskUserQuestion
disable-model-invocation: true
---

You are running `/release` in the **current working directory's repo**. Goal: land the
version bump on the default branch **through a pull request**, like every other change,
and tag the commit that actually merged — in **one run**.

**A tag still cannot be cut before the merge, which is why there is a wait in the
middle.** A tag must point at a commit that exists on the branch you publish from; a
squash-merge replaces the branch's commits with a new one, so a tag created before the
merge names a SHA that never lands. No reordering of the steps fixes that — the commit to
tag does not exist until the request merges. So the run goes *through* the merge instead
of stopping in front of it: it hands the merge to the forge, waits for the bump to appear
on the default branch, and tags what landed.

| Stage | Steps | Ends with |
| --- | --- | --- |
| **Prepare** | 2–9 | the version chosen, the bump and changelog committed on a pushed branch, an open release PR |
| **Land** | 10–11 | auto-merge handed to the forge, and the bump on the default branch |
| **Tag** | 12–13 | the merged commit tagged, the tag pushed, release CI running |

**`phase A` and `phase B` — what step 1a's script reports — name the repo's *state*, not
two runs of this command.** Phase A is "nothing pending"; phase B is "a bump is committed
that no tag names". An ordinary run starts in A, and steps 10–11 are what *put the repo
into B*; step 12 then tags it. A run that starts in B is one finishing a release whose
wait had expired.

**The wait can time out, and then the run hands back rather than half-finishing.** Review
takes as long as it takes and a session does not outlive a weekend; when the wait expires
the run reports the open PR and stops, having created no tag. **Re-running
`/rhiza:release` finishes the release** — step 1a reports phase B and goes straight to
step 12. That is not a special case: it is steps 12–13 entered later, and it is why an
expired wait leaves nothing to undo.

**Never push to the default branch, and never move an existing tag.** The run pushes one
*release branch* — the same thing `/rhiza:init` and `/rhiza:update` do — and then one
*tag*, onto the commit the forge merged.

**The human decision is the version; the checks are the gate.** Step 3 stops and makes a
person choose the bump, because that is the judgement nothing here can make. What follows
is mechanical, so the run carries it through rather than handing back a command to
re-type. What keeps that safe is not a second pair of hands, it is step 12's guard: a
version that does not strictly increase, or a tag that already exists, stops the run
before anything is created. If anything is ambiguous, stop and report.

**Be honest about what auto-merge waits for: `--auto` defers to the *required* checks the
branch has, so a repo with none configured merges the release PR immediately.** On such a
repo one run really is one run, start to published, and the review window is whatever
branch protection actually enforces — not the pause this command used to create by
accident. Say so in the report, and if a repo wants a longer look at its release PR, the
fix is a required check, not a slower command.

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
  default branch yet, **stop and say so** — that includes a release branch a previous run
  opened, which is not tagged until it merges. Every run starts from the default branch;
  the only branch this command is ever *on* is the one it created in step 8.
- **Version config.** `[tool.bumpversion]` must exist, in `.bumpversion.toml` or
  `pyproject.toml`:
  ```bash
  uvx bump-my-version show current_version
  ```
  If that fails, **stop** — the repo hasn't declared where its version lives, and
  guessing is exactly what this command refuses to do. Report what's needed: a
  `.bumpversion.toml` with `current_version` and one `[[tool.bumpversion.files]]` entry
  per location (see step 6 for the stub-pin case). Hold the value as `CURRENT`.
- **Unless the config is tag-derived, which is how Go *and Rust* declare it** — and any
  Python project on `hatch-vcs`, whose `[project]` carries `dynamic = ["version"]` and so
  has no version in a file either. Both `go-core` and `rust-core` ship a
  `.bumpversion.toml` that deliberately omits
  `current_version`: the file is *synced*, so it must not carry a value only the consuming
  repo can own — the next `/rhiza:update` would reset it. Each therefore derives the
  current version from the newest matching tag, and on a repo that has not been tagged yet
  the command above fails with "Unable to determine the current version" — a **declared**
  version location with nothing to read yet, which is not the same fact as no config at
  all and must not be reported as one. Tell them apart:
```bash
grep -lq '^\[tool\.bumpversion\]' .bumpversion.toml pyproject.toml 2>/dev/null
```
  **Hold whether the config is tag-derived, as `TAG_DERIVED` — step 1a needs it and the
  command above does not answer it.** A missing `current_version` is the test, not a
  failing `show`: on a repo that *has* been tagged, `show` succeeds by deriving the
  version from the tag, so the failure only appears before the first release. Read the
  key instead:
```bash
grep -rn '^current_version' .bumpversion.toml pyproject.toml 2>/dev/null
```
  No match, with a `[tool.bumpversion]` table present → tag-derived; pass
  `--tag-derived` in step 1a. This is the case where phase B has no other evidence, so
  getting it wrong is what strands the tag.
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
- **Up to date.** `git fetch --tags origin`, and `git pull --ff-only` so a release PR
  that merged while you were away is actually in your history — step 1a reads the version
  off it.

## 1a. Which state is the repo in?

Almost always this is a fresh release and the answer is phase A. The exception is a run
whose wait expired (step 11): its bump is merged and untagged, and this run finishes it.
The repo's own state says which — and the script decides, so don't compare versions by
eye. Pass `--changelog` always, and `--tag-derived` when step 1 found no
`current_version` to read:

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/check_version_bump.py" \
  --current "$CURRENT" --changelog CHANGELOG.md ${TAG_DERIVED:+--tag-derived}
```

It prints a `phase` line, and in phase B a `target`. Take both as given:

- **`phase A`** — the declared version is released, and nothing is pending. Continue to
  step 2.
- **`phase B`** — a release has landed on the default branch that no tag names: the PR
  merged and only the tag is missing. Take `TARGET` from the script's `target` line, skip
  steps 2–11 entirely, and go to **step 12**. Say which phase it reported and on what
  evidence, so the user can correct you if a hand-edit put the repo here.
- **exit 3, `phase ambiguous`** — the repo's state fits neither. **Stop and report the
  reason line**, which names the disagreement: a version below its own newest tag (a
  reverted bump, or a tag cut ahead of the config), two sources naming different pending
  versions (the PR was edited before merging), or a tag-derived repo with no changelog to
  read. Something rewrote history, and guessing is not this command's job.

**Why the script is given the changelog, and why it is not optional.** The phase is
"is there a version committed to the default branch that no tag names?", and for most
repos `CURRENT` answers it: the bump wrote a number into a manifest, so `CURRENT` >
`highest` exactly when the release PR has merged.

**A tag-derived repo has no such number, and this is where the check used to fail
silently.** When the version *is* the newest tag — Go and Rust as step 1 describes them,
and any Python project on `hatch-vcs` with `dynamic = ["version"]` — `CURRENT` is *read
from* `highest`, so it can never exceed it and phase B is unreachable by construction.
The flow would re-detect phase A after the merge, offer the same menu again, and fail at
step 6 when `bump-my-version` could not find the old version in files already bumped.
The tag was never mis-cut, but the second half of the release could not be run at all.

So `CHANGELOG.md` is the evidence instead: step 7 prepends the new section on the release
branch, so after the merge the newest heading names a version above every tag, and
`--tag-derived` makes the script **refuse** rather than answer "A" when that file is
missing. There is no third source to fall back on — pick the tag by hand at that point.

**This is what makes the flow resumable, and it is why an expired wait costs nothing.**
The merge may happen days later, in a different session; the only state that carries
across is what is committed to the default branch, which is exactly what the script above
reads. Step 11 polls for the same fact from the same evidence — the changelog heading,
through the same parser — so the wait and this check cannot disagree about whether a
release has landed.

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

**On a tag-derived config (Go, Rust, or `hatch-vcs`), add `--current-version "$CURRENT"`.** With no
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

**Do not tag.** The tag belongs on the merged commit, which does not exist yet; step 12
creates it, in this same run. Creating one here is the exact mistake the wait exists to
prevent — a squash-merge would strand it on a SHA that never reaches the default branch.

```bash
git push --set-upstream origin "$BRANCH"
```

## 9. Open the release PR

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
publish the release**: the run that opened it is waiting for the merge and will tag the
merged commit, and if that run has ended, re-running `/rhiza:release` does the same.
Keep the PR URL; steps 11 and 13 report it.

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
>
> On the atomic path there is nothing to merge and nothing to wait for: **skip steps 10
> and 11**, and go from that push to step 13. It is already one run — what it gives up is
> the PR, not the second invocation.

## 10. Hand the merge to the forge

**If step 9 could not open the request at all** — no `gh`/`glab`, or it failed — there is
nothing to merge and nothing to wait for. Skip this step and step 11, report the pushed
branch and the compare URL, and say the release finishes by re-running `/rhiza:release`
once the PR has been opened and merged by hand. Waiting on a request that does not exist
is nine minutes spent proving it.

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/platform_cli.py" \
  pr-merge --head "$BRANCH"
```
That is `gh pr merge "$BRANCH" --squash --auto` on GitHub and `glab mr merge "$BRANCH"
--squash --auto-merge --yes` on GitLab. Don't hand-write either: the two disagree about
the flag's *name* and about what it defers on — gh waits for the branch's required
checks, glab only defers while a pipeline is already running — and glab prompts without
`--yes`, which hangs a non-interactive run rather than failing it.

**Squash, deliberately.** The release is one commit and the changelog section describes
exactly that commit; a merge commit would put the tag on a commit whose *parent* carries
the version.

**Exit 1 here is not fatal, and one cause of it is routine:** a repo with the setting
switched off answers `Auto-merge is not allowed for this repository`. Relay the message
and **continue to step 11 anyway** — the wait does not care who merges, so a human
merging by hand arrives at step 12 by the same road. Two things not to do: don't reach
for `--admin` (it merges past the checks that are this flow's actual gate), and don't
merge the PR yourself with a hand-written `gh`/`glab` call, because then nothing reviewed
the release but the version table.

## 11. Wait for the bump to land on the default branch

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/wait_for_merge.py" \
  --branch "$DEFAULT" --expect-version "${TARGET#v}"
```
It fetches `origin/$DEFAULT` on an interval and reads the newest release heading out of
that branch's `CHANGELOG.md` — the artifact step 7 committed, in every language and on
every config shape, parsed by the same `_rhiza_changelog` that step 1a's phase decision
uses. **What it waits for is the bump landing, not a request merging.** Those are
different claims and only the first is the precondition for a tag: a request can be
closed and re-landed by hand, or merged under a title nobody recognises, without changing
what step 12 needs to be true.

**One call blocks for up to nine minutes** — `--timeout` defaults to 540 seconds and
`--interval` to 20 — because that is what fits inside a single tool call. Allow for it if
your own invocation carries a timeout, and don't raise `--timeout` past ten minutes: the
call would be killed mid-poll, and a killed wait reads as a failure rather than as "not
yet". `--timeout 0` polls once, which is how to ask whether it has landed without waiting
for it to. Read the exit code:

| Exit | Meaning | What to do |
| --- | --- | --- |
| **0** | the bump is on `$DEFAULT` | hold the SHA it reports as `MERGE_SHA`; step 12 |
| **3** | timed out — the release has not merged yet | **stop**; see below |
| **1** | git failed (no `origin`, no network, no such branch) | **stop and report** — nothing was waited for |
| **2** | `--expect-version` wasn't `X.Y.Z` | a caller bug, not a repo problem |

**On exit 3, ask the forge why before deciding anything:**

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/pr_status.py" \
  --branch "$BRANCH"
```
- **Checks still running** — call the wait once more. At most **three waits in total**
  (about 27 minutes); a release whose CI is green in four minutes is the common case and
  is worth waiting out.
- **A check is red** — stop. The release cannot merge until someone fixes it, and that
  someone is not this command: `/rhiza:remote` reads the failure and works on the
  request's own branch.
- **Green but still open** — auto-merge is off or a review is required. Stop; the merge is
  waiting on a person.
- **No request listed at all** — `pr_status.py` asks for `--state open`, so a request that
  merged in the seconds between the wait giving up and this call answers with nothing.
  That is not "the PR vanished", it is very likely "it just landed": re-probe with
  `wait_for_merge.py --branch "$DEFAULT" --expect-version "${TARGET#v}" --timeout 0`
  before handing anything back, and go to step 12 if it now says landed. Only if that
  still reports not-landed is the request genuinely gone — closed unmerged, or the branch
  renamed — and then stop and say so.

Then **hand back**, and say plainly that **no tag exists and nothing is half-done**: the
release is finished by re-running `/rhiza:release` once the PR merges, and step 1a will
report phase B and go straight to step 12. What you must not do is loop the wait
indefinitely — a review that isn't finished is not a timing problem, and an agent asleep
for an hour is not doing the user a service.

## 12. Tag the merged commit

You arrive here two ways, and they differ in exactly one thing: **from step 11 you are
still on the release branch**, because step 8 switched to it, whereas step 1a sends you
here from the default branch. So get onto the merged commit first:

```bash
git switch "$DEFAULT"
git pull --ff-only
```
`--ff-only` is a check, not a convenience: the release commit is the squash of your own
branch onto a `$DEFAULT` you were level with in step 1, so a fast-forward is exactly what
the history should permit. If it refuses, **stop** — something else has landed and your
history and the remote's have diverged, which is not a state to cut a release from.

From step 11, `TARGET` is what you chose in step 3, and the wait has just confirmed the
merged branch names it. From step 1a, `TARGET` is the version it printed on its `target`
line — which is `v$CURRENT` on a repo that writes its version into a file, and the
changelog's newest heading on a tag-derived one.

**Verify you are tagging the right commit before creating anything:**

```bash
git rev-parse --abbrev-ref HEAD
git status --porcelain
git log -1 --format='%H %s'
```
On `$DEFAULT` and clean. **What `HEAD` is does not have to be the release commit**, and
this is the one place where insisting on it would be wrong: a merge that lands while
someone else is also merging leaves the release commit one or two behind the tip within
seconds, through nobody's mistake. The tag names a commit, not a branch position — so
when you came from step 11, tag the SHA the wait identified and check the property the
tag actually needs, which is the same one release CI re-checks:

```bash
git merge-base --is-ancestor "$MERGE_SHA" "origin/$DEFAULT"
```
Non-zero means `MERGE_SHA` is not on the branch you publish from — **stop**, because that
is the orphaned-tag case the whole wait exists to avoid. On the step-1a path there is no
`MERGE_SHA` to check: `HEAD` is the merged commit by construction, since that is what
step 1a read the version off, and the pull above left you level with the remote.

**Confirm the merged tree really carries `TARGET`.** Everything read so far was read
before the merge, so this is a check that the merge preserved it, not a re-read. Run it
on the merged history and require the verdict the repo is now in — `phase B`, with the
same target:

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/check_version_bump.py" \
  --current "$CURRENT" --changelog CHANGELOG.md ${TAG_DERIVED:+--tag-derived} --json
```
`target` must equal `$TARGET`. A mismatch, or a phase that is no longer B, means the PR
was edited before merging — stop and report both values.

**Do not confirm this with `bump-my-version show current_version`.** That was this step's
check and it is only half a check: on a tag-derived repo it reads the *old* tag and so
reports `$CURRENT` — never `$TARGET` — failing every time on a correctly merged release.
The script above is the one source that answers for both repo shapes.

Then guard and tag:

```bash
HIGHEST="$(git tag --list 'v*' | sort -V | tail -1)"
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/check_version_bump.py" \
  "$TARGET" --current "$HIGHEST"
git tag -a "$TARGET" -m "release $TARGET" "${MERGE_SHA:-HEAD}"
```
**The explicit commit is the point**, and the fallback is what makes one line serve both
paths: from step 11 `MERGE_SHA` is the commit the wait watched arrive, and on the step-1a
path it is unset and `HEAD` is that commit already. Tagging a *branch name* would let the
few seconds between the check above and the tag decide which commit gets released.
The guard runs **again**, on the merged history: it is cheap, and while the run was
waiting the repo gained commits and possibly tags, so the fact that `TARGET` was legal in
step 4 is no longer evidence that it is legal now. Non-zero exit means stop. **Never**
`-f`.

**Pass the highest tag, not `$CURRENT` — this is the one place this guard differs from
step 4's.** The script's floor is `max(current, highest tag)`, and in step 4 that is
exactly right: `CURRENT` is the *released* version and `TARGET` has to beat it. Once the
bump has merged, `CURRENT` **is** `TARGET`, and asking it to strictly increase past
itself cannot be satisfied by any version:

```
error  v0.8.0 does not strictly increase past v0.8.0 (current 0.8.0, highest tag v0.7.0)
```

That is not a fluke of one release — passing `$CURRENT` here fails *every* run at this
step and strands the tag permanently. It shipped that way and was caught on the first
real use.

The invariant worth checking has not changed: **do not reuse or move a tag, and do not go
backwards against what is published.** The highest tag is what expresses that once the
declared version has already moved, and the script's refusal of an existing tag still
fires, so a re-tag or a moved tag is still blocked.

Then push it:

```bash
git push origin "$TARGET"
```
Only the tag: the commit is already on the default branch, put there by the merge.
Pushing it triggers release CI.

> **This step pushes; it does not hand the push back.** It used to stop here and ask the
> user to run that line themselves, on the reasoning that publishing should be a
> deliberate human action. That reasoning belonged to an older flow still, where the
> command committed straight to the default branch and the tag push was the *only* gate on
> the whole release.
>
> The PR and its checks are that gate now. A human chose the version and a PR titled
> `chore: release <TARGET>` went green before it merged. Demanding a further deliberate
> act adds a step without adding a decision — and the safety here was never the human's
> hand on the button, it is the guard above refusing an existing tag and refusing a
> version that does not increase.
>
> **If the guard did not pass, none of this runs.** That is the invariant worth protecting,
> and it is unchanged.

## 13. Report

**On a completed release**, concisely: `CURRENT` → `TARGET`, with confirmation that it
strictly increases past every prior release; every file the bump touched (manifests,
`pyproject.toml`, any stub pins, the bumpversion config); the changelog diff summary; the
PR/MR URL and that it merged; the tag, the commit SHA it points at, and that the tag has
been **pushed** — so release CI is running. Link the workflow run and the published
release once it appears. Say how long the wait took, and — when the repo has no required
checks — that the PR merged as soon as it was opened, because that is a fact about the
repo the user may want to change.

To undo a tag that should not have gone out: `git push origin :refs/tags/<TARGET>` and
`git tag -d <TARGET>`, and say plainly that deleting a published tag is disruptive to
anyone who already fetched it. There is no commit to reset, because the bump landed by
merge.

**On a run that stopped at step 11** (the wait timed out, or the merge is blocked): the
same bump and changelog summary, the branch, and the PR/MR URL — then state plainly that
**no tag exists** and the release is not public, that nothing is half-done, and that
re-running `/rhiza:release` after the PR merges finishes it. Name the reason the wait
ended if you know it: red checks are the user's to fix (`/rhiza:remote` reads them), an
un-merged PR is theirs to merge.

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
