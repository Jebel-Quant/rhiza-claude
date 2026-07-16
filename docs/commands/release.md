# `/rhiza:release`

Prepare a release for the current rhiza-managed repo — **locally**. Bumps the
version, bumps any self-referencing workflow-stub pins, regenerates the
changelog, commits, and tags, then stops so you review before pushing.

```
/rhiza:release [version e.g. v1.4.0]
```

With no argument the next version is **derived from the conventional commits**
since the last tag; pass an explicit `vX.Y.Z` to override.

## What it does

1. **Preconditions** — confirms the repo is rhiza-managed, the working tree is
   clean, you're on the default branch (asks if not), and `uvx` is available;
   fetches tags.
2. **Current version** — reads `[project].version` from `pyproject.toml`.
3. **Next version** — `uvx git-cliff --bumped-version` computes the bump
   (`feat` → minor, `fix` → patch, breaking → major); you confirm or override.
   **Guards that the target strictly increases** past every previous release —
   the highest existing tag *and* the current `pyproject.toml` version, compared
   as semver — and refuses to reuse an existing tag.
4. **Preview** — shows the release notes (`git-cliff --unreleased --tag`) before
   writing anything; stops if there's nothing new since the last tag.
5. **Bump** — sets the `pyproject.toml` version (skipped for dynamic versions).
6. **Workflow pins** — bumps any **self-referencing** workflow-stub pins
   (`uses: <this-repo>/…@vX.Y.Z`) to the new tag, so the template repo's own
   stubs move with the release. A no-op for downstream repos (their stubs point
   at `jebel-quant/rhiza`, not at themselves).
7. **Changelog** — rewrites `CHANGELOG.md` with the unreleased commits folded
   under the new tag.
8. **Commit + tag** — `chore: release vX.Y.Z` and a matching local tag.
9. **Stops before pushing** — prints the `git push` commands. Pushing the **tag**
   is what triggers the repo's `Release` workflow to publish.

## Notes

- **Never pushes and never force-tags.** Everything it does is a local commit and
  tag you can undo (`git tag -d …`, `git reset --hard HEAD~1`).
- Meant for a rhiza-managed **application**, not this plugin repo (which releases
  via `make release VERSION=vX.Y.Z`).
- Needs `uvx` for `git-cliff`; no `gh`/`glab` required to prepare — only to
  publish manually if the repo has no release workflow.
