# `/rhiza:release`

Prepare a release **locally**: bump every version location the repo declares,
regenerate the changelog, commit, and tag — then stop so you review before pushing.

```
/rhiza:release [version e.g. v1.4.0]
```

With no argument you get a **menu of candidate versions** — what the conventional commits
imply, plus the patch/minor/major alternatives. Pass an explicit `vX.Y.Z` to skip the menu.
An argument that isn't semver-shaped is treated as a comment, not a target.

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
2. **Gathers candidates** — `git-cliff --bumped-version` for what the commits imply,
   plus the `patch`/`minor`/`major` versions computed from the floor by
   `scripts/check_version_bump.py`, so every option offered is guaranteed legal.
3. **Offers them as a menu** — a list, not one value with an invitation to override,
   because the right bump is a judgement the deriver can't make. The derived option is
   marked recommended and each is labelled with its consequence. See below for why this
   matters most before 1.0.
4. **Guards the choice** — via `scripts/check_version_bump.py`. The floor is the greater
   of the declared current version *and* the highest existing tag, compared **as semver**
   (so `v1.10.0` beats `v1.9.0`), and an existing tag is refused outright. A hand-typed
   value is guarded too.
5. **Previews the release notes** and stops if nothing is unreleased.
6. **Bumps every declared location** — `bump-my-version bump --new-version`, then shows
   `git diff --stat`.
7. **Regenerates `CHANGELOG.md`** with the unreleased commits folded under the new tag.
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

## The pre-1.0 trap

`git-cliff` applies **no pre-1.0 special case**: a single `feat!:` or `BREAKING CHANGE`
footer at `0.x` derives `v1.0.0`. But at `0.x`, semver does not *require* that — going to
1.0 is a deliberate statement of API stability, and spending it by accident is the whole
reason `/release` presents a menu rather than a single derived value. When the repo is
pre-1.0 and the derivation says `v1.0.0`, the minor candidate (e.g. `v0.5.0`) is always
offered alongside, with the trade-off spelled out.

## Why the guard is a separate script

`bump-my-version` accepts a backwards version without complaint and knows nothing about
git tags — verified: `0.4.2 → 0.4.1` exits 0. Since a pushed tag is effectively
permanent, tagging backwards or reusing a tag is the one mistake in this flow that isn't
cheaply reversible, so that single check stays explicit and tested rather than assumed.

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
  `scripts/platform_cli.py release-create`. On GitLab `--notes-file` is **required**:
  `glab` has no `--generate-notes`, so the mapper refuses rather than publishing a
  release with empty notes.
