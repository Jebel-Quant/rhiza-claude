# `/rhiza:tree`

List the files rhiza manages in this repo as a directory tree, then a total
count. Read-only; no scoring, no fixes, no issues.

```
/rhiza:tree [path to a repo root]
```

The optional argument is the repo root to inspect; it defaults to the current
repo.

## What it does

Runs the bundled `scripts/tree.py` — a stdlib-only read of the `files` recorded
in `.rhiza/template.lock` — and renders them as a Unix-`tree`-style view followed
by the count of files managed by Rhiza.

## Notes

- Works without the `rhiza` CLI (and without PyYAML).
- If no `template.lock` is present the repo hasn't been synced yet; run
  `rhiza sync` first. For the metadata behind this file list, see
  [`/rhiza:status`](status.md); for a fuller dashboard, [`/rhiza:stats`](stats.md).
