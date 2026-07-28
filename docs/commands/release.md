# `/rhiza:release`

Prepare a release **locally**: bump every version location the repo declares,
regenerate the changelog, commit, and tag — then stop so you review before pushing.

```
/rhiza:release [version e.g. v1.4.0]
```

With no argument the next version is **derived from the conventional commits** since
the last tag; pass an explicit `vX.Y.Z` to override.

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

1. **Preconditions** — rhiza-managed, clean tree, `[tool.bumpversion]` present (via
   `bump-my-version show current_version`), on the default branch (asks if not), tags
   fetched.
2. **Next version** — `git-cliff --bumped-version` computes the bump: `feat` → minor,
   `fix` → patch, `!`/`BREAKING CHANGE` → major. Note git-cliff applies no pre-1.0
   special case, so a breaking change at `0.x` derives `v1.0.0`.
3. **Guards that it strictly increases** — via `scripts/check_version_bump.py`. The
   floor is the greater of the declared current version *and* the highest existing tag,
   compared **as semver** (so `v1.10.0` beats `v1.9.0`), and an existing tag is refused
   outright.
4. **Confirms with you**, then re-runs the guard on any override.
5. **Previews the release notes** and stops if nothing is unreleased.
6. **Bumps every declared location** — `bump-my-version bump --new-version`, then shows
   `git diff --stat`.
7. **Regenerates `CHANGELOG.md`** with the unreleased commits folded under the new tag.
8. **Commits and tags** locally — `chore: release vX.Y.Z`.
9. **Stops before pushing** — prints the `git push` commands. Pushing the **tag** is
   what triggers the repo's `Release` workflow.

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
search = '(?m)^\[project\]([^\[]*?)version = "{current_version}"'
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
- `scripts/release.sh` (`make release VERSION=vX.Y.Z`) is the agent-free twin, sharing
  the same `[tool.bumpversion]` config and the same guard so the two cannot drift.
- Needs `uvx` for `bump-my-version` and `git-cliff`; no `gh`/`glab` required to prepare.
