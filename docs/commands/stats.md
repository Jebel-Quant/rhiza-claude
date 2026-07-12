# `/rhiza:stats`

A read-only statistics dashboard for the current repo. No scoring, no fixes, no
issues.

```
/rhiza:stats [path or topic to scope the stats to]
```

The optional argument scopes the stats; it defaults to the whole repo.

## What it does

Runs the bundled `scripts/stats.py` (the agent gathers no data itself), which
reports:

- lines of code, lines of tests, and their ratio;
- GitHub/GitLab stars;
- language mix, coverage, and complexity;
- dependency counts and git activity;
- the rhiza template status.

It prints the dashboard to the terminal and writes a self-contained
`docs/stats.html` you can wire into `mkdocs.yml`.

## Notes

- For the authoritative template state it prefers `rhiza status --json`, falling
  back to reading `.rhiza/template.lock` directly.
- Purely descriptive — for a scored assessment use [`/rhiza:quality`](quality.md).
