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

**Non-interactive git.** These run in a non-tty shell, so:
- Any `git` subcommand that can page or read stdin **must** be pinned to a
  revision or piped. In particular `git shortlog` reads commits from **stdin**
  when given no revision — it will hang or return empty (this bit us in a real
  run). Always write `git shortlog -sn --no-merges HEAD` (or `git log --no-merges
  --format='%an' | sort | uniq -c | sort -rn`).
- Prefix pager-prone commands with `git --no-pager` (e.g. `git --no-pager log …`).

**Count tracked files, not the working tree.** Use `git ls-files` as the file
list for LOC and size — **not** `find .`. A `find`-based sweep pulls in
git-ignored runtime state (e.g. in `~/.claude` the working tree is hundreds of MB
of ignored caches/transcripts), which would wildly inflate every count. Scope
`git ls-files` with a pathspec when `$ARGUMENTS` narrows the target.

## 1. Repo identity
- Repo root (`git rev-parse --show-toplevel`), current branch, default branch.
- Platform + `owner/repo` from `git remote get-url origin` (github.com → GitHub; gitlab.com / self-hosted → GitLab; none → say "no remote").
- Project type: `pyproject.toml` present → Python (read `project.name`, version, `requires-python`); else infer from the dominant file extensions.
- **License** — from `pyproject.toml`/`LICENSE` (SPDX id).
- **Repo age & size** — first-commit date → age (see step 6). For size, report the **tracked-tree size** (`git ls-files | xargs du -ch | tail -1`) and the `.git` dir (`du -sh .git`) separately. Do **not** use `du -sh .` on the whole working tree (it includes ignored runtime data) and do **not** pass `du --exclude=…` (unsupported on macOS/BSD `du`). The host's reported disk usage (`gh`'s `diskUsage`, KB) is a good cross-check.
- **Host social stats.** Pull these in one call each where possible; `n/a` if no remote or the platform CLI is unavailable/unauthenticated. **Stars is the headline**, but gather the standard set:
  - GitHub → `gh repo view --json stargazerCount,forkCount,isArchived,licenseInfo,createdAt,pushedAt,diskUsage` (do not add `watchers` here — the field returns an object and is awkward; get watchers/subscribers separately via `gh api repos/OWNER/REPO --jq .subscribers_count`).
  - GitLab → `glab api projects/:id --jq '{stars: .star_count, forks: .forks_count}'`.
  - Report: **stars**, forks, watchers/subscribers, archived flag.

## 2. Code size & language mix
- **Lines of code** by language/extension. Use `scc` or `tokei` **only if the binary is already on `PATH`** (`command -v scc`) — they give a proper code/comment/blank split. Do **not** try `uvx scc`/`uvx tokei`: scc and tokei are Go binaries, not PyPI packages, so `uvx` cannot install them (this failed in a real run). If neither binary is present, the reliable default is a git-tracked line count: `git ls-files | sed 's/.*\.//' | sort | uniq -c | sort -rn` for the extension mix, and `git ls-files '*.<ext>' | xargs wc -l | tail -1` per major extension — say it's a raw line count (blanks/comments included).
- **File counts** for the primary source dirs that exist (`src/`, `tests/`, `docs/`), via `git ls-files <dir> | wc -l`. For a non-Python repo, report counts for whatever top-level dirs actually hold content.
- **Code vs. comments vs. blanks:** only if `scc`/`tokei` ran; otherwise say "raw line count (no code/comment split without scc/tokei)".
- **Definition counts (Python):** number of modules, classes, and functions (`git grep -c '^\s*class ' -- 'src/**.py'`, `git grep -cE '^\s*(async )?def ' -- 'src/**.py'` — roughly). Skip on non-Python repos.
- **TODO/FIXME markers:** `git grep -InE 'TODO|FIXME|XXX|HACK' | wc -l` over tracked files (a debt-smell count, not a judgement).
- **Largest files:** top ~10 by line count (`git ls-files | xargs wc -l | sort -rn | grep -v ' total$' | head`), scoped by a `git ls-files` pathspec when `$ARGUMENTS` is given.
- **Lines of code** (source) and **lines of tests** as distinct headline numbers, counted over tracked files: source = `git ls-files 'src/**' | xargs wc -l | tail -1` (or the repo's primary source dir if there's no `src/`), tests = `git ls-files 'tests/**' | xargs wc -l | tail -1`. For a repo with no conventional source/test split (e.g. a config/docs repo), report total tracked LOC and note that a source/test split doesn't apply.
- **Test-to-code ratio** = test LOC / source LOC, shown as both a ratio (e.g. `0.8:1`) and a percentage — only when both a source and a tests tree exist; otherwise `n/a`.

## 3. Tests & coverage
- **Test count:** number of test functions (`git grep -cE '^\s*(async )?def test_' -- 'tests/**.py' | awk -F: '{s+=$2} END{print s}'`) and test files (`git ls-files 'tests/**test_*.py' | wc -l`), or the collected count from `make test` if cheap. `n/a` if there's no `tests/` dir.
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
- **Contributors:** `git shortlog -sn --no-merges HEAD | head` (top authors by commit count) and total distinct authors (`git shortlog -sn --no-merges HEAD | wc -l`). **The `HEAD` is required** — without a revision, `git shortlog` reads from stdin and returns empty in this non-tty shell.
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
