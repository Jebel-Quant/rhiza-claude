# `/rhiza:repos`

List the GitHub repositories tagged with a rhiza topic as a **JSON document**.
Read-only; no scoring, no fixes, no issues.

```
/rhiza:repos [topic]
```

The optional argument is the GitHub topic to search for; it defaults to `rhiza`.

## What it does

Runs the bundled `scripts/repos.py` — a stdlib-only query of the GitHub Search
API — and emits one JSON document:

```json
{
  "topic": "rhiza",
  "count": 2,
  "repositories": [
    {
      "name": "…",
      "full_name": "…",
      "description": "…",
      "url": "…",
      "topics": ["…"],
      "language": "…",
      "stars": 0,
      "archived": false,
      "updated_at": "…",
      "pushed_at": "…"
    }
  ]
}
```

Repositories are sorted by full name.

## Notes

- Set `GITHUB_TOKEN` to raise the API rate limit.
- Works without the `rhiza` CLI installed — it only needs `python3`.
