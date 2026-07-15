# `/rhiza:init`

Bootstrap a **rhiza-managed repo** in the current folder. Wraps `uv init` for the
project skeleton — you don't need to be in a git repo first (uv creates one).

```
/rhiza:init [repo name]
```

The optional argument is the repository name; it defaults to the current folder's
name.

## What it does

1. **Checks preconditions** — if a `.rhiza/` directory already exists the repo is
   already managed, so `/init` **hands off to [`/rhiza:update`](update.md)** (to
   bring the template to its latest version, never touching an existing
   `template.yml`) and stops. Otherwise it captures any existing git state and
   confirms `uv` is available.
2. **Bootstraps the skeleton with `uv init`** — for Python (the default) it runs
   `uv init --lib`, which creates the git repo, `pyproject.toml`, `src/<pkg>/`,
   `README.md`, `.gitignore`, and `.python-version`. It **skips** `uv init` when a
   `pyproject.toml` already exists. Since `uv init` creates no `tests/`, it then
   seeds a starter module and test via [`/rhiza:new`](new.md) so the coverage gate
   starts green. (Go: `git init` + a `go mod init` hint.)
3. **Asks GitHub vs GitLab** (auto-detecting the host from an existing `origin`),
   then owner / name / visibility.
4. **Picks the template repo** — defaulting to `jebel-quant/rhiza` or
   `jebel-quant/rhiza-go` by the language chosen in step 2, with a reachability
   check.
5. **Scaffolds the rhiza-only config** via `scripts/init_scaffold.py`:
   `.rhiza/template.yml`, a bootstrap `Makefile`, and — optionally — `mkdocs.yml`.
   The project skeleton already came from `uv init`, so the scaffolder no longer
   writes `pyproject.toml`/`src/`/`README.md`.
6. **Runs the first sync, validates, tests**, then puts everything on a
   `rhiza_init_<date>` branch and **opens a PR** — never pushing rhiza changes
   straight to the default branch.

## Prerequisites

[`uv`](https://docs.astral.sh/uv/) is required (for `uv init` and `uvx`). Install
it once with `curl -LsSf https://astral.sh/uv/install.sh | sh` — or just run
`/rhiza:init`, which **offers to install `uv`** for you (with your approval) if
it's missing.

## Notes

- Only for repos that **aren't** rhiza-managed yet; an existing `.rhiza/` routes
  to [`/rhiza:update`](update.md).
