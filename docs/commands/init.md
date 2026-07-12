# `/rhiza:init`

Bootstrap a **rhiza-managed repo** in the current folder — empty, or an existing
git repo that isn't managed yet.

```
/rhiza:init [repo name]
```

The optional argument is the repository name; it defaults to the current folder's
name.

## What it does

1. **Detects the starting state** — aborts if the repo is already rhiza-managed
   (use [`/rhiza:boost`](boost.md) instead); otherwise handles both an empty
   folder and an existing `.git` (with commits and/or an `origin` remote).
2. **`git init`** only when there's no repo yet — never re-inits or renames an
   existing branch.
3. **Asks GitHub vs GitLab** (auto-detecting the host from an existing `origin`),
   then owner / name / visibility for a brand-new repo.
4. **Picks language and template repo** — Python or Go, defaulting to
   `jebel-quant/rhiza` or `jebel-quant/rhiza-go`, with a reachability check
   before writing anything.
5. **Scaffolds the project** via the bundled `scripts/init_scaffold.py`:
   `.rhiza/template.yml`, a bootstrap `Makefile`, and — optionally — the Python
   skeleton (`pyproject.toml` + `src/` + `tests/`), `mkdocs.yml`, and a real
   starter `README.md`. Creates only what's missing; never overwrites.
6. **Validates** the config, then puts the scaffold and the first template sync
   on a `rhiza_init_<date>` branch and **opens a PR** — never pushing rhiza
   changes straight to the default branch.

## Notes

- The bootstrap `Makefile` self-installs rhiza (`uvx rhiza sync .`) until the
  first sync writes `.rhiza/rhiza.mk`, so `make sync` works even on a brand-new
  repo.
- The scaffolder is a stdlib-only port of what `rhiza init` produced, verified
  against the template's own bundled tests — the path to retiring `rhiza init`.
