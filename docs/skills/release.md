# `/rhiza:release`

Land a release **through a pull request**, in one run: bump every version location the
repo declares, regenerate the changelog, open a release PR, let the forge merge it once
its checks pass, and tag the commit that actually landed.

```
/rhiza:release [version e.g. v1.4.0]
```

With no argument you get a **table of candidate versions** — patch, minor and major,
each with what it means and which commits point at it. It does **not** suggest one, mark
one recommended, or default to one: picking the bump is your call. Pass an explicit
`vX.Y.Z` to skip the table. An argument that isn't semver-shaped is treated as a comment,
not a target.

!!! important "The repo declares where its version lives"
    `/release` does not scan for version-shaped strings. It runs
    [`bump-my-version`](https://github.com/callowayproject/bump-my-version), which
    reads `[tool.bumpversion]` from `.bumpversion.toml` or `pyproject.toml` and rewrites
    **only** the explicit search/replace patterns listed there.

    That's what makes it safe to bump a `pyproject.toml` version, a plugin manifest and
    a self-referencing CI pin in one step **without** touching a dependency that happens
    to share the current version number. If the config is missing, `/release` **stops**
    rather than guessing — [skeleton](../internals/skeleton.md) scaffolds it for new
    repos.

## What it does

1. **Preconditions** — clean tree, `[tool.bumpversion]` present (via
   `bump-my-version show current_version`), on the default branch (asks if not), tags
   fetched, and the commits being released actually on that branch. It does **not**
   require `.rhiza/`: nothing in the release flow comes from the template, which is why
   this works on the plugin repo too.
2. **Gathers candidates** — the `patch`/`minor`/`major` versions computed from the floor
   by `plugin/scripts/check_version_bump.py`, so every option offered is guaranteed legal, plus
   a count of the unreleased `feat`/`fix`/breaking commits as evidence for the table.
3. **Prints them as a table** — every legal candidate in ascending order, each labelled
   with its consequence and the commits pointing at it, then asks you to choose. No
   recommended row, no default, no ordering that implies one. See below for why.
4. **Guards the choice** — via `plugin/scripts/check_version_bump.py`. The floor is the greater
   of the declared current version *and* the highest existing tag, compared **as semver**
   (so `v1.10.0` beats `v1.9.0`), and an existing tag is refused outright. A hand-typed
   value is guarded too.
5. **Previews the release notes** and stops if nothing is unreleased.
6. **Bumps every declared location** — `bump-my-version bump --new-version`, then shows
   `git diff --stat`.
7. **Prepends a `CHANGELOG.md` section** for the unreleased commits, labelled with the
   new tag, then checks the diff touches nothing else. See below for why it prepends.
8. **Commits the bump on a release branch** — `chore: release vX.Y.Z`, on a branch from
   [pr-base](../internals/pr-base.md), pushed. **No tag yet.**
9. **Opens the release PR.**
10. **Hands the merge to the forge** — `gh pr merge --squash --auto`, or
    `glab mr merge --squash --auto-merge --yes`, through
    `plugin/scripts/platform_cli.py pr-merge`. A repo with auto-merge switched off just
    says so; the run continues, because the next step doesn't care who merges.
11. **Waits for the bump to reach the default branch** —
    `plugin/scripts/wait_for_merge.py` fetches `origin/<default>` on an interval and reads
    the newest release heading out of that branch's `CHANGELOG.md`, through the same
    parser the phase decision uses. It waits for **the bump landing**, not for a request
    merging, because that is what the tag needs to be true. Nine minutes per call, up to
    three calls while the PR's checks are still running.
12. **Tags the merged commit and pushes the tag.** That push triggers the repo's
    `Release` workflow.

    The version is the human decision and the checks are the gate: you picked the bump
    from the table, and a PR titled `chore: release vX.Y.Z` went green before it merged.
    What keeps the tag safe is step 12's guard — a version that doesn't strictly increase,
    or a tag that already exists, stops the run before anything is created.
13. **Reports** the release, or — if the wait ran out — the open PR, with the tag
    explicitly not created.

!!! warning "Don't let CI tag it as well — this repo tried, and removed it"
    If the repo owns its CI, a workflow on push-to-default can tag a merged release
    itself: when the declared version is ahead of the highest tag, tag the merged commit
    and publish. That condition is one of the two `/release` uses to read the repo's state
    — and it is blind on a tag-derived repo, where nothing is ever ahead of the tag — and
    it is self-limiting: after tagging, declared equals highest, so every ordinary merge
    that follows is a no-op. This repo ran exactly that, and removed it.

    The reason still applies, and now applies more sharply: **it does not replace the tag
    step, it races it.** The command tags the merge it just waited for, so a workflow doing
    the same thing means two things creating one ref — whichever loses gets
    `Reference already exists (HTTP 422)`, a failed run, and a release that actually
    succeeded sitting under a red check. A step that must happen exactly once needs exactly
    one entry point.

    Two further traps if you still want it: a ref pushed with `GITHUB_TOKEN` does **not**
    trigger further workflow runs, so the auto-created tag publishes nothing unless the
    publishing workflow is invoked explicitly (`workflow_call`) rather than left to its
    tag-push trigger — and that second entry point then has to be maintained too.

## Why there's a wait in the middle

The version bump is an ordinary change and goes through review like any other, which
means the default branch is never pushed to directly and required checks actually gate
the release. But a tag has to name a commit **on** the default branch, and a squash-merge
replaces the branch's commits with a new one — so a tag cut before the merge points at a
SHA that never lands.

No reordering fixes that: the commit worth tagging does not exist until the PR merges. It
used to be you who bridged that gap, by running the command a second time. Now the run
bridges it — it asks the forge to merge the PR when its checks pass, then waits for the
bump to appear on the default branch.

**The wait is bounded, and running out is an ordinary outcome.** Each call waits nine
minutes — what fits inside one tool call — and `/release` repeats it only while the forge
says the PR's checks are still running, at most three times. A red check, or a green PR
nobody has merged, ends the wait immediately, because neither is something more waiting
fixes. Then the run reports the open PR and stops with **no tag created**, and re-running
`/release` finishes the release.

It knows where it stands from the repo itself — you never tell it. The question is "is a
version committed to the default branch that no tag names?", and
`check_version_bump.py` answers it, so the state is read off a `phase` line rather than
compared by eye:

| State | Meaning | What it does |
| --- | --- | --- |
| declared version **==** highest tag, nothing pending | the declared version is released | **phase A** — bump, changelog, PR, merge, tag |
| a committed version **>** highest tag | a merged bump no tag names | **phase B** — tags the merged commit, target taken from the script |
| declared version **<** highest tag, or two sources disagreeing | reverted bump, a tag cut ahead, or a PR edited before merge | stops and reports the reason (exit 3) |

**Those two names are states of the repo, not two runs of the command.** An ordinary run
starts in A, and its own merge is what puts the repo into B, which it then tags. A run
that *starts* in B is one finishing a release whose wait had expired — and that verdict is
the only state carried between runs, so the merge can happen days later, in a different
session, and the next run still knows what to do.

!!! warning "`--auto` waits for *required* checks — and a repo with none merges at once"
    Auto-merge defers to whatever branch protection actually enforces. Where nothing is
    required, the release PR is opened and merged within the same run, and "one step" is
    literal. That is not the command being hasty: it is the repo having no gate, which was
    equally true before, just hidden behind the pause of waiting for a second invocation.
    If you want a longer look at a release PR, make a check required.

    On GitLab the flag differs and so does its meaning: `glab mr merge --auto-merge`
    defers only while a pipeline is *already running*, and merges immediately when none is.
    Both platforms mean "merge when the forge will allow it"; only GitHub's is a gate.

### Where the committed version is, when it isn't in a file

For most repos the declared version *is* the evidence: `bump-my-version` wrote a number
into a manifest, so it exceeds the highest tag exactly when the release PR has merged.

**A tag-derived repo has no such number.** When the version is the newest tag — Go and
Rust, whose synced `.bumpversion.toml` deliberately omits `current_version`, and any
Python project on `hatch-vcs` with `dynamic = ["version"]` — the declared version is
*read from* the highest tag, so it can never exceed it. Phase B was unreachable for those
repos by construction: the flow re-detected phase A after the merge and offered the same
menu again. No tag was ever mis-cut, but the second half of the release could not be run.

So `CHANGELOG.md` is the evidence instead. Step 7 prepends the new section on the release
branch, so after the merge its newest heading names a version above every tag — and on a
tag-derived repo the run **refuses** rather than assuming nothing is pending when it is
missing, because there is no third source to fall back on.

## The one repo that can't use a PR

When CI stubs delegate via `uses: <owner>/<repo>/…@vX.Y.Z` and the repo being released
**is** that repo — the stub-pin case `/release` bumps in step 6 — the release PR
references a tag that does not exist yet. A cross-repo `uses:` resolves at `Set up job`,
before checkout, so every job dies before running anything:

```
##[error]Unable to resolve action `owner/repo@vX.Y.Z`, unable to find version `vX.Y.Z`
```

The failures are indistinguishable from real breakage at a glance, yet nothing in the diff
is at fault — the jobs never got as far as checking out code. Required checks can therefore
never go green, and the PR is unmergeable except by bypassing branch protection.

`/release` detects the self-pin **before** opening a PR that cannot merge, and asks. The
fallback commits and tags on the default branch directly, pushing both refs with
`git push --atomic origin HEAD <TAG>` — atomic because two sequential pushes leave a
window where the branch is published and the tag is not, and every run started in it fails
as above.

On that path there is nothing to merge and nothing to wait for, so steps 10–11 are
skipped: it is already a single run, and what it gives up is the pull request, not a
second invocation.

The durable fix belongs in the repo, not here: reference your own action by local path
(`uses: ./.github/actions/<name>`), which needs no tag, cannot drift, and makes the repo
releasable by PR like every other.

## Why it doesn't suggest a version

Deriving the bump from conventional commits looks decidable and isn't. `git-cliff
--bumped-version` will happily turn a single `feat!:` or `BREAKING CHANGE` footer at `0.x`
into `v1.0.0` — it applies **no pre-1.0 special case**. But at `0.x` semver does not
*require* that: going to 1.0 is a deliberate statement of API stability, and it can only
be spent once. Nothing in the commit log records whether you're ready to spend it.

So `/release` gathers the evidence and stops there. The table shows every legal candidate
with the commits behind it — including, pre-1.0, both `v1.0.0` and the `minor` candidate
with the trade-off spelled out — and the choice stays yours. A recommendation here would
be a guess wearing the clothes of a derivation, and the one that lands as an accidental
1.0 is not reversible.

## Why the guard is a separate script

`bump-my-version` accepts a backwards version without complaint and knows nothing about
git tags — verified: `0.4.2 → 0.4.1` exits 0. Since a pushed tag is effectively
permanent, tagging backwards or reusing a tag is the one mistake in this flow that isn't
cheaply reversible, so that single check stays explicit and tested rather than assumed.

## Why the changelog is prepended, not regenerated

`git-cliff --output CHANGELOG.md` rebuilds the entire file from the commits reachable
from `HEAD`. That reachability is the trap: a tag stops being reachable whenever its
branch is squash-merged, rebased, or deleted after release — all routine — and a
regeneration then **drops that release's section entirely** and re-files its commits
under the next reachable version. The output looks plausible, the diff quietly rewrites
history that already shipped, and nobody re-reads old changelog entries at release time.

Releasing `rhiza-hooks` v1.1.0 hit it: the full regeneration deleted `## [0.7.0]` and
moved its two commits into `0.7.1`.

`--unreleased --tag "$TARGET" --prepend CHANGELOG.md` writes only the new section and
leaves everything below it byte-identical, which is why `/release` diffs the result and
refuses to commit a change that reaches further. One caveat that follows from prepending:
it is not idempotent, so a repeat run needs `git checkout CHANGELOG.md` first.

## Anchor your `pyproject.toml` pattern

`search`/`replace` apply to **every** occurrence in a file, so the obvious form also
rewrites a `[tool.something].version` sharing the number. Confine it to `[project]`:

```toml
[[tool.bumpversion.files]]
filename = "pyproject.toml"
regex = true
search = '(?ms)^\[project\]((?:(?!^\[)[\s\S])*?)^version = "{current_version}"'
replace = '[project]\1version = "{new_version}"'
```

Dependency pins (`httpx>=1.2.0`) are never at risk either way — they aren't
line-anchored `version = ` assignments — but a second `[tool.*]` table is.

## Self-referencing CI stubs

Rhiza ships CI as thin stubs delegating via `uses: <owner>/<repo>/.github/…@vX.Y.Z`.
When the repo being released *is* the one those stubs point at, the pin must move with
the release, or the published tag ships workflows calling the **previous** version's
reusable workflows. That's one config entry per stub — and if `/release` spots such a
self-reference the config doesn't cover, it stops and says so. Third-party pins
(`actions/checkout@v5`) and floating refs (`@main`) are never rewritten.

## Notes

- **Never pushes to the default branch, and never force-tags.** It pushes two things: the
  release branch — the same thing [`/rhiza:init`](init.md) and [`/rhiza:update`](update.md)
  do — and then the tag, onto the commit the forge merged. Before the merge, the whole
  thing is undone by deleting the branch; after the tag, by deleting the tag.
- **The wait needs no forge CLI.** It is `git fetch` against `origin` and a read of the
  merged `CHANGELOG.md`, so a repo whose `gh`/`glab` is missing or logged out still gets
  it — you merge the PR in the browser and the run tags what lands.
- **Works for this plugin too.** It reads the version from wherever the config points,
  so a repo with no `pyproject.toml` (like this one, whose version lives in the two
  `.claude-plugin/` manifests) is handled the same way.
- **This is the only release path.** A `scripts/release.sh` used to duplicate it for
  agent-free use, from the same `[tool.bumpversion]` config and the same guard. It was
  removed once this command dropped its `.rhiza/` requirement and moved to
  `bump-my-version`, because from that point the two did the same work — and the shell
  copy was the one executable in the repo with no test and no `shellcheck` hook, while
  every bundled script is gated at 100% coverage.
- Needs `uvx` for `bump-my-version` and `git-cliff`, and `gh`/`glab` to open the PR —
  if the forge CLI is missing the branch is still pushed, so you can open it by hand.
- Publishing manually (only needed when the repo has no release workflow) goes through
  `plugin/scripts/platform_cli.py release-create`. On GitLab `--notes-file` is **required**:
  `glab` has no `--generate-notes`, so the mapper refuses rather than publishing a
  release with empty notes.

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/skills/release/SKILL.md` |
| **Invocation** | `/rhiza:release [version e.g. v1.4.0]  (optional; omit to pick from a table of candidates)` |
| **Model-invocable** | no — excluded from model invocation |
| **Allowed tools** | `Bash(git*)`, `Bash(gh*)`, `Bash(glab*)`, `Bash(uv*)`, `Bash(uvx*)`, `Bash(make*)`, `Bash(cat*)`, `Bash(grep*)`, `Read`, `Edit`, `AskUserQuestion` |

<!-- generated:end -->
