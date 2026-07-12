# `/rhiza:validate`

Validate the repo's `.rhiza/template.yml`. Exits non-zero on failure.

```
/rhiza:validate [path to a repo root]
```

The optional argument is the repo root to inspect; it defaults to the current
repo.

## What it does

Runs the bundled `scripts/validate.py` — stdlib-only — and checks that:

- the target is a git repository with the expected language-specific structure;
- `.rhiza/template.yml` exists and parses;
- its required and optional fields — `repository`, `profiles` / `templates` /
  `include`, `ref`, `host`, `language`, `exclude` — are present and well-typed.

## Notes

- Works without the `rhiza` CLI installed.
- Used by [`/rhiza:init`](init.md) as its final gate before opening the PR, so a
  freshly scaffolded config is never shipped broken.
