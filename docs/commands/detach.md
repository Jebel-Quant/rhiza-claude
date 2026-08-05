# `/rhiza:detach`

Detach the repo from rhiza by removing every rhiza-managed file.

!!! warning "Destructive"
    This deletes files. It prompts for confirmation unless `--force` is passed.

```
/rhiza:detach [path to a repo root]
```

The optional argument is the repo root to operate on; it defaults to the current
repo.

## What it does

Runs the bundled `plugin/scripts/detach.py` — stdlib-only — which:

- deletes every file listed in `.rhiza/template.lock`,
- prunes the directories left empty by those deletions,
- removes the lock file itself.

## This detaches a repo, not the plugin

The two sound similar and are unrelated. Neither substitutes for the other:

| | What it removes | Where the effect lands |
| --- | --- | --- |
| `/plugin` → uninstall | The rhiza plugin itself | Your Claude Code installation |
| `/rhiza:detach` | Files rhiza synced *into a repo* | A codebase, as a commit |

Uninstalling the plugin leaves every synced file sitting in each managed repo — the CI
workflows, `Makefile`, `rhiza.mk`, the docs base, `.rhiza/template.lock`. They keep
working; there is simply nothing left that maintains them. Conversely `/rhiza:detach`
strips one repo clean and leaves the plugin installed, which is what you want when you
are releasing a single project from template management but still using rhiza elsewhere.

So this is the inverse of the **sync**, not of the **installation**.

## Notes

- Works without the `rhiza` CLI installed.
- Undoes what a sync materialized; it does not touch your own hand-written files
  (only those tracked in the lock).

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/skills/detach/SKILL.md` |
| **Invocation** | `/rhiza:detach [path to a repo root]  (optional; defaults to the current repo)` |
| **Model-invocable** | no — excluded from model invocation |
| **Allowed tools** | `Bash(uv*)`, `Bash(python3*)`, `Read` |

<!-- generated:end -->
