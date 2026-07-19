---
description: Prepare a release for the current rhiza-managed repo — derive the next semantic version from the conventional commits since the last tag (via git-cliff, overridable), guard that it strictly increases past every previous release, bump the project version in pyproject.toml, bump any self-referencing workflow-stub pins to the new tag, regenerate CHANGELOG.md folding the unreleased commits under the new tag, then commit and tag locally. Stops before pushing: it prints the push commands so you review first, and the tag push is what triggers the release CI. Never pushes or force-tags on its own.
argument-hint: "[version e.g. v1.4.0]  (optional; defaults to the git-cliff-derived bump)"
allowed-tools: Bash(git*), Bash(uv*), Bash(uvx*), Bash(make*), Bash(python3*), Bash(cat*), Bash(grep*), Bash(sed*), Read, Edit, AskUserQuestion
---

You are running `/release` in the **current working directory's repo** — a
rhiza-managed application (not this plugin repo). Goal: prepare a clean,
reviewable release **locally** — bump the version, bump self-referencing
workflow pins, regenerate the changelog, commit, and tag — then **stop and hand
the push back to the user**. Pushing the tag is what triggers the repo's release
workflow, so that step stays a deliberate, human action.

**Never push, and never move an existing tag.** This command only writes to the
working tree and creates a local commit + tag. If anything is ambiguous, stop
and report rather than guessing.

Argument (optional): `$ARGUMENTS` — an explicit version like `v1.4.0`. If empty,
derive it from the conventional commits (step 3).

## 1. Preconditions
- **Rhiza-managed?** Confirm `.rhiza/template.yml` (or `.rhiza/template.lock`)
  exists. If not, this isn't a rhiza repo — stop and say so.
- **Clean tree.** `git status --porcelain`; if dirty, stop and show the dirty
  files. A release must be cut from committed work.
- **On the default branch.** `git branch --show-current` vs the remote default
  (`git remote show origin` / `gh repo view --json defaultBranchRef`). If you're
  not on it, warn and ask (`AskUserQuestion`) whether to continue — releasing off
  a side branch is unusual but not forbidden.
- **Tooling.** Confirm `uvx` is available (needed for `git-cliff`). If missing,
  stop with the fix (`install uv`) — the version derivation and changelog both
  depend on it.
- **Up to date.** `git fetch --tags origin` so tag checks and the commit range
  see the real history.

## 2. Find the current version
Read the project version from `pyproject.toml` — the `[project]` table's
`version` field:
```bash
grep -m1 '^version' pyproject.toml
```
Hold it as `CURRENT` (bare, e.g. `1.3.2`). If `pyproject.toml` has no static
`version` (e.g. it's dynamic/VCS-derived), note that — you'll skip the bump in
step 5 and rely on the tag alone, but say so explicitly.

## 3. Decide the next version — and prove it strictly increases
First establish the **version floor**: the highest version already released, so
a new tag can only ever move the project forward. Read the highest existing tag:
```bash
git tag --list 'v*' --sort=-v:refname | head -1   # e.g. v1.1.3
```
`FLOOR` = the greater of `CURRENT` (step 2, as `vCURRENT`) and that highest tag,
**compared as semver** — not as strings, so `v1.10.0 > v1.9.0`.

- **If `$ARGUMENTS` is a version** (`vX.Y.Z`), use it as `TARGET`. Validate it
  starts with `v` and is semver-shaped.
- **Otherwise derive it** from the conventional commits since the last tag:
  ```bash
  uvx git-cliff --bumped-version
  ```
  This returns the computed next tag (major/minor/patch bump per the commit
  types). Hold it as `TARGET`.
- **Strictly-increasing guard (hard requirement).** `TARGET` **must be strictly
  greater than `FLOOR`**, compared as semver. If it is equal to or below any
  previous release version or the current `pyproject.toml` version, **stop and
  report** — never tag a version that doesn't move forward. Likewise, if
  `refs/tags/$TARGET` already exists (local or remote), stop — do not overwrite
  or move it. A reliable comparison (avoids string pitfalls like `1.9 > 1.10`):
  ```bash
  uv run --python 3.12 --no-project python - "$TARGET" "$FLOOR" <<'PY'
  import sys
  def parse(v): return tuple(int(x) for x in v.lstrip("v").split("."))
  target, floor = parse(sys.argv[1]), parse(sys.argv[2])
  if target <= floor:
      sys.exit(f"error: {sys.argv[1]} does not strictly increase past {sys.argv[2]}")
  print(f"ok: {sys.argv[1]} > {sys.argv[2]}")
  PY
  ```
- **Confirm with the user** (`AskUserQuestion`): show `CURRENT`, `FLOOR`, the
  derived `TARGET`, and a one-line rationale (the commit types that drove the
  bump — `feat` → minor, `fix` → patch, a `!`/`BREAKING CHANGE` → major). Offer
  the derived value first (recommended) and let them override. Re-run the guard
  above on any overridden value. Never tag without this confirmation.

`BARE="${TARGET#v}"` for the pyproject bump.

## 4. Preview the release notes
Show what will land in the changelog for this tag so the user sees it before
anything is written:
```bash
uvx git-cliff --unreleased --tag "$TARGET"
```
If it's empty (no unreleased commits), stop and report — there's nothing to
release since the last tag.

## 5. Bump the version (pyproject.toml)
Unless the version is dynamic (step 2), set `[project].version` to `$BARE`.
Use `Edit` for a surgical change to the single `version = "…"` line — do not
reformat the file. Re-read the line to confirm it now reads `$BARE`.

## 6. Bump self-referencing workflow pins
Rhiza distributes CI as thin **workflow stubs** that delegate to reusable
workflows/actions via `uses: <owner>/<repo>/.github/…@vX.Y.Z`. When the repo
being released is *itself* the one those stubs point at (i.e. the rhiza template
repo), the pinned ref has to move with the release — otherwise the published tag
ships workflows that still call a **previous** version's reusable
workflows/actions (the drift that left `pyproject.toml` at `1.1.3` while the
stubs still pinned `@v0.19.9`).

Bump every **self-referencing** semver pin to `$TARGET` — only pins whose
`owner/repo` equals *this* repo. Leave third-party pins (`actions/checkout@v7`,
…) and cross-repo pins untouched, and leave non-semver refs (`@main`, a commit
SHA) alone.

Derive this repo's slug from the remote, then rewrite the pins:
```bash
SLUG=$(git remote get-url origin | sed -E 's#(git@[^:]+:|https?://[^/]+/)##; s#\.git$##')
```
```bash
uv run --python 3.12 --no-project python - "$SLUG" "$TARGET" <<'PY'
import re, sys, pathlib
slug, target = sys.argv[1], sys.argv[2]
# match `uses: <slug>/<path>@vX.Y.Z`; case-insensitive (uses: is case-insensitive)
pin = re.compile(r'(uses:\s*' + re.escape(slug) + r'/[^@\s]+@)v\d+\.\d+\.\d+', re.IGNORECASE)
changed = []
for p in sorted(pathlib.Path(".github").rglob("*")):
    if p.is_file() and p.suffix in (".yml", ".yaml"):
        text = p.read_text()
        new, n = pin.subn(lambda m: m.group(1) + target, text)
        if n:
            p.write_text(new)
            changed.append(f"{p}: {n} pin(s) -> {target}")
print("\n".join(changed) if changed else "no self-referencing workflow pins (nothing to bump)")
PY
```
This is a **no-op for downstream repos** — their stubs point at
`jebel-quant/rhiza`, not at themselves — and only rewrites pins in the template
repo. Show `git diff --stat -- .github` so the user sees exactly which stubs
moved. (A GitLab repo carries the analogous self-reference as `include: …
ref: vX.Y.Z` in `.gitlab-ci.yml`; apply the same rule there if present.)

## 7. Regenerate the changelog
Fold the unreleased commits under the new tag and rewrite `CHANGELOG.md`:
```bash
uvx git-cliff --tag "$TARGET" --output CHANGELOG.md
```
(equivalently `make changelog` if the repo's target passes `--tag`; the explicit
`git-cliff` call above is the reliable form since plain `make changelog` usually
omits the unreleased tag.) Show a short diff summary of `CHANGELOG.md`.

## 8. Commit and tag (locally)
- `git add pyproject.toml CHANGELOG.md .github` — the last picks up any
  workflow-pin edits from step 6 (a no-op if none changed; the tree was clean
  before this run, so nothing unrelated is staged).
- `git commit -m "chore: release $TARGET"`
- `git tag "$TARGET"` — an **annotated** tag is fine too
  (`git tag -a "$TARGET" -m "release $TARGET"`); never `-f`.

## 9. Stop — hand the push to the user
Do **not** push. Print the exact next commands and what they do:
```bash
git push origin HEAD      # the release commit
git push origin <TARGET>  # the tag — triggers the release workflow
```
Explain that pushing the **tag** is what triggers the repo's release CI (the
`Release` workflow on a `v*` tag) to publish the GitHub/GitLab release. If the
repo has no such workflow, they can publish manually with
`gh release create <TARGET> --generate-notes` (GitHub) or
`glab release create <TARGET>` (GitLab).

## 10. Report
Summarise concisely: `CURRENT`/`FLOOR` → `TARGET` and why (the derivation
rationale, and that it strictly increases past every previous release), the
files changed (`pyproject.toml`, `CHANGELOG.md`, and any workflow stubs whose
self-referencing pins were bumped to `$TARGET`), the release commit SHA, the tag
created, and the two push commands from step 9. Make clear that **nothing has
been pushed** and the release isn't public until the user pushes the tag. If they
want to undo, the local steps are reversible: `git tag -d <TARGET>` and
`git reset --hard HEAD~1` (mention only if relevant).
