# `/rhiza:uninstall`

Remove all rhiza-managed files from the repo.

!!! warning "Destructive"
    This deletes files. It prompts for confirmation unless `--force` is passed.

```
/rhiza:uninstall [path to a repo root]
```

The optional argument is the repo root to operate on; it defaults to the current
repo.

## What it does

Runs the bundled `scripts/uninstall.py` — stdlib-only — which:

- deletes every file listed in `.rhiza/template.lock`,
- prunes the directories left empty by those deletions,
- removes the lock file itself.

## Notes

- Works without the `rhiza` CLI installed.
- Undoes what a sync materialized; it does not touch your own hand-written files
  (only those tracked in the lock).
