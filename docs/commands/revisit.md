# `/rhiza:revisit`

Create or **revisit** the repo's top-of-tree documentation: `README.md` (with the
full standard rhiza badge set), `CLAUDE.md`, and `mkdocs.yml`.

```
/rhiza:revisit [readme | claude | mkdocs | all]
```

The optional argument limits the run to one file; it defaults to `all`.

## What it does

1. **Detects repo identity and metadata** — reads the git remote,
   `pyproject.toml`, workflow files, and `.rhiza/` config at runtime (never
   hardcoding owner/repo).
2. **Creates the files if missing**, or **revisits** them if present:
   - refreshes the badge block,
   - adds missing standard sections,
   - corrects drift (wrong owner/repo, dead workflow name, changed template
     version).
3. **Preserves hand-written prose** — existing sections, tables, and ordering are
   authoritative; nothing is deleted to "standardize" it. Uses `Edit` over
   `Write` on existing files so diffs stay reviewable.
4. **Syncs the README's `make help` target list** — if the repo has a `Makefile`
   with a `help` target, refreshes the fenced code block that follows the
   `` Run `make help` to see all available targets: `` marker with live, cleaned
   `make help` output (ANSI codes and recursive-make chatter stripped). Idempotent,
   and a no-op when there's no `Makefile`/`help` target or no marker in an existing
   README. This folds in what the retired rhiza-tools `update-readme` command did.

## Notes

- Auto-detects the platform (GitHub/GitLab) for the correct badge and page URLs.
- This is the tool to reach for after [`/rhiza:init`](init.md) scaffolds a bare
  starter README.
