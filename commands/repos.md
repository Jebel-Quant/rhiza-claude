---
description: List the GitHub repositories tagged with a rhiza topic (default `rhiza`) as a JSON document — name, full name, description, URL, topics, language, stars, archived flag, and timestamps. Runs the bundled scripts/repos.py (a stdlib-only query of the GitHub Search API), so it works without the rhiza CLI installed. Read-only; no scoring, no fixes, no issues.
argument-hint: "[topic]  (optional; defaults to 'rhiza')"
allowed-tools: Bash(uv*), Bash(python3*), Read
---

You are running `/repos` to discover the rhiza-tagged repositories on GitHub.

**This command is a thin wrapper around the bundled `scripts/repos.py`.** All the
API querying and JSON shaping lives in that script — a deterministic, stdlib-only
Python program that hits the GitHub Search API directly (no `rhiza` CLI required).
Do **not** re-implement the fetch or hand-build the JSON yourself; run the script
and relay its output.

This is purely descriptive — it **lists what exists; it does not score, fix, or
file anything**.

Argument (optional): `$ARGUMENTS` — a GitHub topic to search for; default is
`rhiza`.

## 1. Run the script
Invoke it with the plugin-root path (it ships inside this plugin, so
`${CLAUDE_PLUGIN_ROOT}` resolves at runtime — **keep the quotes**). Pass the
topic argument as `--topic` only when `$ARGUMENTS` is non-empty:

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/repos.py" ${ARGUMENTS:+--topic "$ARGUMENTS"}
```

- The GitHub Search API rate-limits unauthenticated requests. If `GITHUB_TOKEN`
  is set in the environment the script uses it automatically — mention it if the
  call is rate-limited.

## 2. If the script can't run
- If `${CLAUDE_PLUGIN_ROOT}` is empty (e.g. you're in a source checkout of this
  repo, not an installed plugin), fall back to the repo-relative path:
  `uv run --python 3.12 --no-project python scripts/repos.py ${ARGUMENTS:+--topic "$ARGUMENTS"}`.
- If `uv` is missing, or the script is genuinely not found at either path,
  report that plainly and stop — don't hand-roll the query as a substitute.

## 3. Relay the results
- Show the script's JSON output as-is — it's a single JSON document with `topic`,
  `count`, and a `repositories` array.
- If the script exited non-zero, relay the stderr line (a network or API
  failure); suggest setting `GITHUB_TOKEN` if it looks rate-limited.
- A `count` of `0` is not an error — it just means no repositories carry that
  topic yet.
- No scores or recommendations. For a single repo's template state, point the
  user at `/status`; for a full stats dashboard, `/stats`.
