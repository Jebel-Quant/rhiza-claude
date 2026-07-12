# `/rhiza:quality`

Run the Rhiza code-quality gate and score the current repo, then optionally file
findings as issues.

```
/rhiza:quality [path or topic to scope the assessment to]
```

The optional argument scopes the assessment; it defaults to the whole repo.

## What it does

1. **Runs the quality gates** (cheapest first) — lint, types, docs, deps,
   security, tests, complexity, and architecture — adapting to whichever repo it
   runs in.
2. **Scores 1–10** across the eight subcategories, with an overall score and the
   highest-leverage improvement called out.
3. **Produces actionable findings** — one per subcategory scoring below 10, each
   with a self-contained title, the current→target score, the specific
   file(s)/config, a `done when…` acceptance criterion, and an evidence snippet.
4. **Optionally files issues** for the findings (deduped), unless invoked in
   assessment-only mode (as [`/rhiza:boost`](boost.md) does).

## Notes

- Respects the locally-owned-vs-Rhiza-owned scoping rule, so template-managed
  files aren't scored against you.
- Assessment-only by default when driven from `boost`; it files no issues and
  applies no code fixes there.
