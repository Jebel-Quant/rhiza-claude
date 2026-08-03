# `/rhiza:release`

Prepare a release **locally**: bump every version location the repo declares,
regenerate the changelog, commit, and tag — then stop so you review before pushing.

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
8. **Commits and tags** locally — `chore: release vX.Y.Z`.
9. **Stops before pushing** — prints a single `git push --atomic origin HEAD <TAG>`.
   Pushing the **tag** is what triggers the repo's `Release` workflow.

## Why the push is atomic

Two sequential pushes (branch, then tag) open a window in which the branch is published
but the tag is not. A repo whose workflows reference **their own** tag — the stub-pin case
`/release` bumps in step 6 — fails every run started in that window, because a cross-repo
`uses:` resolves at `Set up job`, before checkout:

```
##[error]Unable to resolve action `owner/repo@vX.Y.Z`, unable to find version `vX.Y.Z`
```

The failures are indistinguishable from real breakage at a glance, yet nothing in the diff
is at fault — the jobs never got as far as checking out code. `--atomic` lands both refs
together so the tag exists before any workflow is queued.

This also makes a release **PR-able**. With sequential pushes and a self-pin, a release PR
carries refs to a tag that does not exist yet, so its required checks can never go green
and the release can only land by bypassing branch protection. The durable fix belongs in
the repo: reference your own action by local path (`uses: ./.github/actions/<name>`), which
needs no tag and cannot drift.

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

- **Never pushes and never force-tags.** Everything is a local commit and tag you can
  undo (`git tag -d …`, `git reset --hard HEAD~1`).
- **Works for this plugin too.** It reads the version from wherever the config points,
  so a repo with no `pyproject.toml` (like this one, whose version lives in the two
  `.claude-plugin/` manifests) is handled the same way.
- **This is the only release path.** A `scripts/release.sh` used to duplicate it for
  agent-free use, from the same `[tool.bumpversion]` config and the same guard. It was
  removed once this command dropped its `.rhiza/` requirement and moved to
  `bump-my-version`, because from that point the two did the same work — and the shell
  copy was the one executable in the repo with no test and no `shellcheck` hook, while
  every bundled script is gated at 100% coverage.
- Needs `uvx` for `bump-my-version` and `git-cliff`; no `gh`/`glab` required to prepare.
- Publishing manually (only needed when the repo has no release workflow) goes through
  `plugin/scripts/platform_cli.py release-create`. On GitLab `--notes-file` is **required**:
  `glab` has no `--generate-notes`, so the mapper refuses rather than publishing a
  release with empty notes.

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/commands/release.md` |
| **Invocation** | `/rhiza:release [version e.g. v1.4.0]  (optional; omit to pick from a table of candidates)` |
| **Model-invocable** | no — excluded from model invocation |
| **Allowed tools** | `Bash(git*)`, `Bash(uv*)`, `Bash(uvx*)`, `Bash(make*)`, `Bash(cat*)`, `Bash(grep*)`, `Read`, `Edit`, `AskUserQuestion` |

<!-- generated:end -->
