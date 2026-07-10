---
description: Report a read-only statistics dashboard for the current repo — lines of code, lines of tests and their ratio, GitHub/GitLab stars, plus language mix, coverage, complexity, dependency counts, git activity, and rhiza template status. No scoring, no fixes, no issues.
argument-hint: "[path or topic to scope the stats to]  (optional; defaults to the whole repo)"
allowed-tools: Bash(git*), Bash(gh*), Bash(glab*), Bash(make*), Bash(find*), Bash(wc*), Bash(grep*), Bash(sort*), Bash(uniq*), Bash(head*), Bash(cat*), Bash(sed*), Bash(awk*), Bash(du*), Bash(uv*), Bash(uvx*), Bash(pip*), Bash(python3*), Read, Glob, Grep
---

You are running `/global_rhiza_stats` in the **current working directory's repo**.
Goal: gather and present a concise **statistics dashboard** for this repo. This is
purely descriptive — it **counts and measures, it does not score, fix, or file
anything**. (That's the division of labour: `/global_rhiza_quality` judges and
scores; `/global_rhiza_stats` just reports the numbers.) Adapt to whatever repo it
runs in by reading its tree, `pyproject.toml`, git history, and `.rhiza/` config at
runtime — don't hardcode paths or assume Python.

Argument (optional): `$ARGUMENTS` — a path or topic to scope the stats to (e.g.
`src/foo`); default is the whole repo.

Follow the command-execution policy: prefer bare `make <target>`; never call
`.venv/bin/...` directly. Everything here is read-only. If a tool is missing,
report "n/a (tool unavailable)" for that metric rather than failing the whole run.

## 1. Repo identity
- Repo root (`git rev-parse --show-toplevel`), current branch, default branch.
- Platform + `owner/repo` from `git remote get-url origin` (github.com → GitHub; gitlab.com / self-hosted → GitLab; none → say "no remote").
- Project type: `pyproject.toml` present → Python (read `project.name`, version, `requires-python`); else infer from the dominant file extensions.
- **License** — from `pyproject.toml`/`LICENSE` (SPDX id).
- **Repo age & size** — first-commit date → age (see step 6); on-disk size of the working tree (`du -sh . --exclude=.git`) and the `.git` dir separately.
- **Host social stats.** Pull these in one call each where possible; `n/a` if no remote or the platform CLI is unavailable/unauthenticated. **Stars is the headline**, but gather the standard set:
  - GitHub → `gh repo view --json stargazerCount,forkCount,watchers,isArchived,licenseInfo,createdAt,pushedAt,diskUsage` (watchers/subscribers via `gh api repos/OWNER/REPO --jq .subscribers_count`).
  - GitLab → `glab api projects/:id --jq '{stars: .star_count, forks: .forks_count}'`.
  - Report: **stars**, forks, watchers/subscribers, archived flag.

## 2. Code size & language mix
- **Lines of code** by language/extension. Prefer `uvx scc .` or `uvx tokei .` (they exclude blanks/comments and honour `.gitignore`); if neither is available, fall back to `find . -name '*.<ext>' -not -path './.git/*' | xargs wc -l` per major extension and say the count is raw line count.
- **File counts** for the primary source dirs (`src/`, `tests/`, `docs/`).
- **Code vs. comments vs. blanks:** if `scc`/`tokei` ran, report the code / comment / blank line split and the comment ratio; else skip.
- **Definition counts (Python):** number of modules, classes, and functions (`grep -rc '^\s*class ' src`, `grep -rc '^\s*def \|^\s*async def ' src` — roughly), plus average function length if cheap.
- **TODO/FIXME markers:** `grep -rIn 'TODO\|FIXME\|XXX\|HACK' src tests | wc -l` (a debt smell count, not a judgement).
- **Largest modules:** top ~10 by line count (`find src -name '*.py' | xargs wc -l | sort -rn | head`), scoped by `$ARGUMENTS` when given.
- **Lines of code** (source, i.e. `src/` or the primary source dir excluding tests) and **lines of tests** (`tests/`) reported as distinct headline numbers.
- **Test-to-code ratio** = test LOC / source LOC, shown as both a ratio (e.g. `0.8:1`) and a percentage, if both exist.

## 3. Tests & coverage
- **Test count:** number of test functions/files (`grep -rc 'def test_' tests | ...`, or the collected count from `make test` if cheap).
- **Coverage:** the configured threshold (`COVERAGE_FAIL_UNDER` in config) and, if a recent `coverage`/`.coverage`/`coverage.xml` artifact exists, the current total — read it rather than re-running the suite. Only run `make test` for a live number if the user's `$ARGUMENTS` asks for it or no artifact exists **and** you note that it's the slow path.
- **Docstring coverage:** the interrogate percentage — read a cached report if present, else `uvx interrogate -q src` (or `make docs-coverage`). Number only, no grade.

## 4. Complexity metrics (Python)
- `uvx radon cc src -a -s` → average cyclomatic complexity and the count of C-or-worse blocks (list the worst few as `file:line`).
- `uvx radon mi src -s` → maintainability-index distribution (how many modules below A).
- Report as numbers only — no grading. If radon is unavailable, say so and skip.

## 5. Dependencies
- Counts from `pyproject.toml`: runtime deps, dev/optional deps, and the number of pinned/locked packages (`uv.lock`/`requirements*.txt` line count if present).
- Python version support range from `requires-python`/classifiers.
- **Outdated deps (optional, if quick):** count from `uv pip list --outdated` (or `pip list --outdated`) — number of packages behind latest; skip if it needs network and would be slow.

## 6. Git activity
- **Commits:** total (`git rev-list --count HEAD`), and last-30-days / last-90-days counts (`git rev-list --count --since=...`).
- **Contributors:** `git shortlog -sn --no-merges | head` (top authors by commit count) and total distinct authors.
- **Recency & age:** first commit date (→ repo age), last commit date, and commit count on the current branch ahead of the default branch.
- **Tags & releases:** tag count (`git tag | wc -l`); latest release tag and its date (`gh release list -L 1` / `glab release list`), and total release count if cheap.
- **Open PRs / MRs:** `gh pr list --state open --json number --jq length` (GitHub) / `glab mr list --opened` count (GitLab). Report alongside open issues so the two aren't conflated.
- **CI status:** the latest default-branch run result (`gh run list -L 1 --json conclusion,name` / GitLab pipeline status) — pass/fail/pending, purely informational.
- **Branches:** total count. Local + remote via `git branch -a --no-color | grep -v HEAD | wc -l`, and remote-only via `git branch -r | grep -v HEAD | wc -l` — report the remote count as the meaningful "how many branches exist" number (run `git fetch --prune` first only if the user asks; otherwise note the count may be stale).
- **Open issues:** the count on the host:
  - GitHub → `gh issue list --state open --limit 1 --json number` won't give a total; use `gh api repos/OWNER/REPO --jq .open_issues_count` (note: GitHub's `open_issues_count` includes open PRs — subtract the open-PR count from `gh pr list --state open` if you want issues-only, and say which you're reporting).
  - GitLab → `glab api projects/:id --jq .open_issues_count`.
  - `n/a` if no remote or the CLI is unavailable/unauthenticated.
- **Churn (optional, if quick):** most-changed files over the last 90 days (`git log --since=90.days --name-only --pretty=format: | sort | uniq -c | sort -rn | head`).

## 7. Rhiza template status
- Template content version (`.rhiza/template.yml` `ref`/`template-branch`) and the tool version (`.rhiza/.rhiza-version`) — report both, noting they're decoupled.
- **Behind latest?** `gh release list -R jebel-quant/rhiza -L 1 --json tagName --jq '.[0].tagName'` → compare to the current `ref` and report "on latest" or "N releases behind / older tag" (best-effort; skip if `gh` unauthenticated).
- Number of files synced from the template (`files:` block length in `.rhiza/template.lock`, if present) vs. locally-owned source files — a rough owned-vs-synced split.
- Active `profiles:` (github-project / gitlab-project / local).

## 8. Present the dashboard
Render a compact, skimmable report — grouped headers with the numbers, small
tables where they help (largest modules, top contributors). Lead with a
**headline block** carrying the metrics the user cares about most, up top:

- **Lines of code** (source) and **lines of tests**, and their **test-to-code ratio**
- **Stars** (GitHub/GitLab)
- **Open issues** and **branches**
- **Commits** (total, plus last-90-days)

Then a one-line summary, e.g. `<name> — <LOC> LOC / <T> test LOC (ratio <R>),
<S>★, <I> open issues, <B> branches, <C> commits, rhiza <ref>`. Follow with the
detailed sections. Mark any metric that couldn't be gathered as `n/a` with the reason.
Do **not** editorialize into scores or recommendations — that's
`/global_rhiza_quality`'s job; point the user there if they want an assessment.
