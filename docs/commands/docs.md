# `/rhiza:docs`

Create or refresh the repo's three top-of-repo documentation files: **`README.md`**,
**`CLAUDE.md`**, and **`mkdocs.yml`**.

```
/rhiza:docs [readme | claude | mkdocs | all]
```

The optional argument limits the run to one file; it defaults to all three.

!!! note "Renamed from `/rhiza:revisit`"
    Same command, clearer name — it's named for what it touches rather than for the
    posture it takes.

!!! important "It refreshes; it does not clobber"
    Existing prose, tables, and section order are authoritative. `/docs` only replaces
    the *generated* badge block, *adds* missing standard sections, and *corrects* stale
    facts (wrong owner/repo, dead workflow name, changed template version). A
    hand-written section is never deleted to standardise it — it's reported instead.
    Existing files are edited, not rewritten, so the diff stays reviewable.

## What it does

1. **Detects the repo's facts** — platform and owner/repo from the git remote, the
   default branch, project metadata from `pyproject.toml`, the template `ref` from
   `.rhiza/template.yml`, the CI workflow file, the licence, a coverage service,
   visibility, and whether the repo uses ruff and uv. Nothing is hardcoded. The
   default branch and visibility come from `plugin/scripts/platform_cli.py repo-view`, which
   normalises the two CLIs' disagreeing shapes — `gh` answers `PUBLIC`, `glab`
   `public` — and so answers on GitLab, which the bare `gh repo view` it replaced
   could not.
2. **Renders the badge block** via `plugin/scripts/render_badges.py`, which enforces **omit,
   don't fake**: a badge whose backing fact wasn't detected is never emitted, and every
   omission comes back with a reason for the report. So a README never advertises a
   workflow, licence, or coverage service that doesn't exist.
3. **Writes or refreshes the README body** — scaffolding `Installation`, `Usage`,
   `Development`, `License` when the file is new; otherwise adding only *missing*
   standard sections.
4. **Syncs the `make help` target block** via `plugin/scripts/sync_readme_help.py` — see
   below.
5. **Writes or refreshes `CLAUDE.md`** — build commands, architecture read from the
   real tree, and the **locally-owned vs. Rhiza-owned** split that
   [`/rhiza:quality`](quality.md)'s scoring depends on. Never contains secrets, tokens,
   or machine-local paths.
6. **Writes or refreshes `mkdocs.yml`** — the *locally owned* site metadata and `nav`,
   inheriting theme and plugins from the synced `docs/mkdocs-base.yml`. It skips
   entirely if the repo doesn't build docs with MkDocs, and never edits the synced
   base — drift there is fixed upstream.

## The `make help` block

The README's list of `make` targets is kept in lockstep with the real `Makefile`, so
contributors never read a stale list. `plugin/scripts/sync_readme_help.py` finds the marker
line — `` Run `make help` to see all available targets: `` — and the fenced block right
after it, then replaces **only that block's contents** with sanitised live `make help`
output (ANSI colour and recursive-make chatter stripped).

- **Idempotent.** Against an unchanged `Makefile` a second run writes nothing.
- **No marker, no Makefile, or no `help` target ⇒ no-op**, reported as `skipped`. It
  never invents a place to put the list, so a hand-written README stays byte-identical.
- It's the one part of the README that must not be hand-edited — the script's
  byte-level contract is what keeps re-runs clean.

## Notes

- **Nothing is committed.** No branch, no PR — the files are left in the working tree
  for you to review and stage.
- A dirty working tree is fine, but the report tells you what your docs changes are
  mixed in with.

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/commands/docs.md` |
| **Invocation** | `/rhiza:docs [readme | claude | mkdocs | all]  (optional; defaults to all)` |
| **Model-invocable** | yes |
| **Allowed tools** | `Bash(git*)`, `Bash(gh*)`, `Bash(glab*)`, `Bash(grep*)`, `Bash(find*)`, `Bash(cat*)`, `Bash(head*)`, `Bash(make*)`, `Bash(uv*)`, `Read`, `Edit`, `Write`, `AskUserQuestion` |

<!-- generated:end -->
