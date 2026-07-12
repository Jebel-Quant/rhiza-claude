# `/rhiza:status`

Show the current rhiza **sync status** for the repo. Read-only; no scoring, no
fixes, no issues.

```
/rhiza:status [path to a repo root]
```

The optional argument is the repo root to inspect; it defaults to the current
repo.

## What it does

Runs the bundled `scripts/status.py` — a stdlib-only read of
`.rhiza/template.lock` — and reports:

- the template repository and ref,
- the synced commit SHA and timestamp,
- the sync strategy,
- the templates / paths that were materialized.

Pass `--json` for a machine-readable object whose fields mirror
`rhiza status --json`.

## Notes

- Works without the `rhiza` CLI (and without PyYAML) — it reads the lock directly.
- If no `template.lock` is present the repo hasn't been synced yet; that's a hint,
  not an error.
