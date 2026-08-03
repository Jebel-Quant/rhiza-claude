# `/rhiza:update`

Sync the repo to a template release and open a PR containing **only template-owned
files**.

```
/rhiza:update [version e.g. v1.2.0]
```

The optional argument pins an explicit template version tag; it defaults to the
template's latest release.

!!! important "Only template files are touched"
    The sync records exactly which paths it materialized in `.rhiza/template.lock`'s
    `files` list. That list — plus `.rhiza/template.yml` and the lock itself — is the
    complete set `/update` stages. It never runs `git add --all`, so your own source,
    tests, and dependencies are never swept into a template PR. Anything else that
    changed is left in the working tree and reported.

## What it does

1. **Preconditions** — follows [install-uv](../internals/install-uv.md) first (the
   sync runs through `uv run`), then confirms the repo is rhiza-managed
   (`.rhiza/template.yml` exists) and the working tree is clean. Notes the branch you
   started on, the default branch, and the hosting platform.
2. **Resolves the target ref** — the given tag, or the latest release of **the
   template repo named in `template.yml`** (so a fork bumps to its own tags, not
   `jebel-quant/rhiza`'s). Major-version jumps require
   confirmation.
3. **Branches off the up-to-date default branch**, then bumps the `ref` in
   `.rhiza/template.yml` and commits. `profiles:`, `templates:` and the rest are left
   alone — switching a platform profile is a separate, deliberate change, not
   something a version bump does.
4. **Runs the bundled `scripts/sync.py`** and interprets its exit code: 0 clean, 1
   synced-with-conflicts (expected, not fatal), 2 a real failure that stops the run
   with nothing applied.
5. **Resolves conflicts** with `scripts/resolve_conflicts.py`, which takes the upstream
   (template) side of every marker block. A `*.rej` file is reported, never applied, and
   stops the run for a human — though the merge no longer produces one, since nothing
   runs `git apply --reject` any more.
6. **Stages only the lock's `files`**, commits, and **opens the PR/MR** through
   `scripts/platform_cli.py`, which maps the operation onto `gh pr create` or
   `glab mr create` — they differ in subcommand, flag names, and whether a body can
   come from a file at all.
7. **Reports** and returns to the branch you started on.

## Notes

- **No gates, no scorecard, no issues.** `/update` syncs; run
  [`/rhiza:quality`](quality.md) when you want the 1–10 scorecard. In particular it
  never runs `make fmt`, which would rewrite the repo's own files and violate the
  template-only rule.
- Bumps the **template content** version (`ref` / `template-branch`).
- [`/rhiza:status`](status.md) shows what's synced afterwards.

<!-- generated:begin — rendered by scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `commands/update.md` |
| **Invocation** | `/rhiza:update [version e.g. v1.2.0]  (optional; defaults to the template's latest release)` |
| **Model-invocable** | yes |
| **Allowed tools** | `Bash(git*)`, `Bash(gh*)`, `Bash(glab*)`, `Bash(uv*)`, `Bash(cat*)`, `Bash(grep*)`, `Read`, `Edit`, `AskUserQuestion` |

<!-- generated:end -->
