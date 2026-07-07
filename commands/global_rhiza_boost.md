---
description: Bump the current repo to the latest (or given) rhiza release, sync the template, resolve conflicts upstream, run the rhiza_quality gates, open a PR with a quality scorecard, and (after confirmation) file one issue per below-10 scorecard finding on the repo's platform (GitHub or GitLab), deduped against existing open issues.
argument-hint: "[version e.g. v0.19.9]  (optional; defaults to latest release)"
allowed-tools: Bash(git*), Bash(gh*), Bash(glab*), Bash(make*), Bash(python3*), Bash(cat*), Bash(grep*), Read, Edit, Write, AskUserQuestion, Skill
---

You are running `/global_rhiza_boost` in the **current working directory's repo**. Goal: bump this one repo to a rhiza release, apply the template sync, resolve any conflicts by taking the upstream side, run the project's quality gates, and open a PR that includes a quality scorecard. Mirror the per-repo flow of `update_rhiza_versions.py` but resolve the version dynamically.

Argument (optional): `$ARGUMENTS` — an explicit template version tag like `v0.19.9`. If empty, use the latest release.

**Important — two independent version fields.** `.rhiza/template.yml`'s `template-branch`/`ref` is the *template content* version (tracks `jebel-quant/rhiza` releases). `.rhiza/.rhiza-version` is the *rhiza tool* version (tracks `rhiza-cli` releases, currently pinned at `0.18.0` across all repos). They are NOT the same number and must not be derived from each other. This command bumps **only the template `ref`** and leaves `.rhiza-version` untouched.

Work through these steps. Stop and report if any precondition fails.

## 1. Preconditions
- Confirm `.rhiza/template.yml` exists in the repo root. If not, abort: "Not a rhiza-managed repo (no .rhiza/template.yml)."
- Confirm the working tree is clean (`git status --porcelain`). If dirty, stop and show the dirty files — do not proceed over uncommitted work.
- Note the current branch and default branch (`gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`, fallback `main`).
- Note the **hosting platform** from `git remote get-url origin` (contains `github.com` → GitHub; `gitlab.com` or a self-hosted GitLab host → GitLab) and the current `profiles:` + `templates:` in `.rhiza/template.yml`. These are the "findings" for the platform menu in step 3.

## 2. Resolve target version
- Read the current `template-branch` (or `ref`) from `.rhiza/template.yml`.
- TARGET:
  - If `$ARGUMENTS` is non-empty, use it verbatim as the tag (ensure it starts with `v`).
  - Else run `gh release list -R jebel-quant/rhiza -L 1 --json tagName --jq '.[0].tagName'` for the latest release tag.
- **Safety:** if TARGET's major version is greater than the current `template-branch`/`ref`'s major (e.g. jumping `v0.19.x` → `v1.x`), STOP and ask the user to confirm before continuing — major bumps are not automatic.
- If TARGET equals the current `template-branch`/`ref`, the version file won't change. Tell the user it's already on TARGET and ask whether to re-run `make sync` anyway (to re-apply template content); stop unless they confirm.

## 3. Choose platform profile (GitHub vs GitLab)
The `profiles:` field in `.rhiza/template.yml` selects which platform's CI gets materialized on sync. Rhiza (`jebel-quant/rhiza`, `.rhiza/template-bundles.yml`) defines three:
- **`github-project`** → `core, github, book, marimo, tests, github-book, github-marimo, github-tests` (syncs `.github/workflows/*`, no GitLab files)
- **`gitlab-project`** → `core, gitlab, book, marimo, tests, gitlab-book, gitlab-marimo, gitlab-tests` (syncs `.gitlab-ci.yml` + GitLab pipelines, no `.github/` files)
- **`local`** → `core, book, marimo, tests` (no hosted CI)

Present the **findings** from step 1 and ask the user with an `AskUserQuestion` menu which platform to configure. Build the menu so the **detected-host option is listed first and marked "(Recommended)"** — e.g. if `origin` is on `github.com`, recommend GitHub. Options:
- **GitHub** → set `profiles: [github-project]`
- **GitLab** → set `profiles: [gitlab-project]`
- **Keep current** → leave `profiles:` as found (the default if the current profile already matches the detected host — you may skip the menu entirely in that case and just report the match)

If the choice **differs** from the current profile, also reconcile platform-specific entries in the `templates:` list: convert `github-*` ↔ `gitlab-*` where an equivalent bundle exists (e.g. `github-marimo` ↔ `gitlab-marimo`, `github-book` ↔ `gitlab-book`), and for entries with no cross-platform equivalent (e.g. `github-devcontainer`, `github-docker`, `github-paper`) list them and ask the user whether to drop them. Don't silently delete platform config.

## 4. Edit template.yml (version + profile)
- Set `template-branch:` (or `ref:`, whichever key is present) to `"<TARGET>"`.
- If step 3 chose a different platform, set `profiles:` (and any reconciled `templates:`) accordingly.
- Do NOT touch `.rhiza/.rhiza-version` — it is the decoupled tool version (see note above).

## 5. Branch + commit the bump
- `BRANCH=rhiza_<TARGET>`
- Create/checkout the branch: `git checkout -b "$BRANCH"` (if it already exists locally, `git checkout "$BRANCH"`).
- `git add .rhiza/template.yml`
- `git commit -m "chore: bump rhiza to <TARGET>"` (if step 3 switched platform, append `" (switch to <github|gitlab>-project)"` to the message)
- `git push --set-upstream origin "$BRANCH"`

## 6. Sync the template
- Run `make sync`. A non-zero exit is expected when there are conflicts — do not treat it as fatal; capture the output and continue.

## 7. Resolve conflicts (take upstream)
- Run `python3 ~/.claude/scripts/rhiza_resolve.py` from the repo root. It replaces conflict markers with the upstream side and applies any `.rej` files, staging what it fixes.
- Sanity check: `grep -rl '^<<<<<<< ' . --exclude-dir=.git` should return nothing. If it still finds markers, list those files and resolve them manually (keep the upstream/theirs side).

## 8. Quality assessment (delegate to `global_rhiza_quality`)
Run the quality gates and produce the scorecard by **invoking the `global_rhiza_quality` command** (via the Skill tool) — 
do **not** re-specify the gates, scoring rubric, or scoping rule here. `global_rhiza_quality` already 
encapsulates the correct gate set (`src/`-aware coverage downstream vs. the mother repo's `make rhiza-test`), the locally-owned-vs-Rhiza-owned scoping rule, and the platform, adapting to whichever repo it runs in. Delegating is what keeps this command from drifting as the template evolves — the single reason for this step's existence.

Invoke it in **assessment-only, boost mode** — pass these constraints when you invoke it:
- Run **all** gates (cheapest first, bare `make <target>` per the command-execution policy) even after an early failure, then produce (a) the per-gate PASS/FAIL summary, (b) the 1–10 scorecard, and (c) the actionable findings list — then **stop**.
- Apply **no** code fixes beyond what `make fmt` auto-formats, and file **no** issues. `global_rhiza_boost` owns issue filing in step 11 (with dedup), and a template-bump PR must not carry surprise code edits. `global_rhiza_quality` is assessment-only by default; if it surfaces an issue-filing menu (as it may in the mother repo), decline it.

`make fmt` may auto-format files during the gate run; that's expected — those fixes get folded into the sync commit in step 9.

From `global_rhiza_quality`'s output, capture for the later steps:
- the **per-gate PASS/FAIL table** → PR body (step 10);
- the **rendered scorecard** (1–10 subcategories + overall + highest-leverage improvement) → PR body (step 10);
- the **findings list**, one per subcategory scoring below 10. Step 11 files these as issues, so ensure each finding carries: a self-contained **title** (e.g. `Raise test coverage on src/foo.py from 84% to 100%`), the **subcategory** and **current→target** score, the specific **file(s)/lines or config**, a crisp **`done when…`** acceptance criterion, and a one-line **evidence** snippet from the gate output. If `global_rhiza_quality` omits the evidence line, augment each finding with it from the captured gate output. Order by leverage (biggest score gain for least effort first).

Persist both artifacts for the next steps: write the scorecard to `$SCRATCHPAD/rhiza_boost_pr_body.md` and the findings to `$SCRATCHPAD/rhiza_boost_findings.md` if a scratchpad path is available, else hold them in context.

> **Note (rhiza ≥ v1.0.0):** if `global_rhiza_quality` runs both `make validate` and `make test` and the full `pytest` session appears inside the `make validate` output, the suite ran twice. That is now an upstream `rhiza_quality`/template concern — flag it, don't patch it here.

## 9. Commit + push sync
- `git add --all` to stage all sync output (new/modified template files) **and** any `make fmt` auto-fixes from step 8.
- If `git diff --cached --name-only` is non-empty:
  - `git commit -m "chore: apply rhiza sync <TARGET>"`
  - `git push`
- Else report "nothing new after sync".

## 10. Open PR (with scorecard)
- Compose the PR body: the summary, the per-gate PASS/FAIL table, and the full 1–10 scorecard + recommendations from step 8. Write it to a file and pass `--body-file` (the scorecard is too long for inline `--body`):
  ```
  gh pr create \
    --title "chore: update rhiza to <TARGET>" \
    --base <DEFAULT_BRANCH> --head "$BRANCH" \
    --body-file <PR_BODY_FILE>
  ```
  The body should open with:
  ```
  ## Summary
  - Bumps the template `ref`/`template-branch` to `<TARGET>` in `.rhiza/template.yml`
  - Platform profile: `<github-project|gitlab-project|local>` (note here if step 3 switched platforms)
  - Runs `make sync` to apply upstream template changes; conflicts resolved taking upstream

  ## Quality gates
  <per-gate PASS/FAIL table>

  ## Scorecard
  <1–10 subcategory scores + overall + highest-leverage improvement + recommendations>
  ```
- If the PR already exists, update its body (`gh pr edit <BRANCH> --body-file <PR_BODY_FILE>`) and report the existing URL instead of erroring.

## 11. File issues for below-10 findings (after confirmation, with dedup)
The findings from step 8 also live in the PR scorecard, but `global_rhiza_boost` owns filing them as tracked issues — `global_rhiza_quality` deliberately skipped its own issue-filing menu because it was invoked in boost mode. Do this here:

- **Dedup first.** List the repo's existing open issues so you don't file duplicates:
  - GitHub → `gh issue list --state open --limit 200 --json number,title --jq '.[] | "#\(.number) \(.title)"'`
  - GitLab → `glab issue list --opened --per-page 200`
  - For each step-8 finding, compare its title against the open issues; treat a clear title/subject match as already-filed. Mark such findings as "(already open: #N)" and exclude them from the default selection.
- **Confirm via menu, not free text.** Present the not-already-filed findings as an `AskUserQuestion` multi-select (`multiSelect: true`), one option per finding labelled by its title, so the user picks exactly which to file — including none. Create nothing without an explicit selection. If every finding is already open (or there are none), say so and skip the menu.
- **File each selected finding** with the platform CLI detected in step 1 (GitHub → `gh issue create`, GitLab → `glab issue create`; skip and say so if that CLI is unavailable or unauthenticated). Make each issue self-contained, carrying from the finding: the **title**, the **subcategory** and **current→target** score, the specific **file(s)/lines or config** to change, the **`done when…`** acceptance criterion, and the one-line **evidence** snippet from the gate output. Reference the PR (`<PR_URL>`) in the body for context.
- Collect the created issue URLs for the report.

## 12. Report
Summarize: target version, platform profile (and whether it was switched), branch, conflicts/`.rej` resolved, files changed, the gate PASS/FAIL line, the overall score, the PR URL, and the issues filed (URLs) or skipped-as-duplicate / declined. Keep it short.
