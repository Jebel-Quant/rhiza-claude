# `/rhiza:status`

Report the repo's **rhiza state** — both halves of it. Read-only; no scoring, no
fixes, no issues.

```
/rhiza:status [path to a repo root] [--files] [--check]
```

The optional argument is the repo root to inspect; it defaults to the current repo.

!!! note "Absorbed `/rhiza:validate`"
    Config validation used to be its own command. It reported half the picture, and
    its name collided with `make validate` — a *different* check (project structure
    against the template) that [`/rhiza:quality`](quality.md) runs. `scripts/validate.py`
    is unchanged and still exits non-zero on an invalid config, so it remains usable
    as a CI gate.

## The two halves

| half | file | question |
| --- | --- | --- |
| **config** | `.rhiza/template.yml` + repo structure | is what we'd sync *from* well-formed? |
| **sync** | `.rhiza/template.lock` | what was actually synced, and when? |

Intent versus outcome — and they can disagree in both directions, which is why
reporting one without the other misleads. A freshly [`/rhiza:init`](init.md)-ed repo
has a valid config and **no lock at all**. A long-synced repo can have a lock
alongside a config someone has since broken by hand.

## What it does

1. **Validates the configuration** via `scripts/validate.py` — that the target is a
   git repo with the expected language-specific structure (a `pyproject.toml` is
   required for Python), that `.rhiza/template.yml` exists and parses, and that its
   required and optional fields (`repository`, `profiles`/`templates`/`include`, `ref`,
   `host`, `language`, `exclude`) are present and well-typed. A failure is reported as
   a finding rather than stopping the run, since a broken config next to a good lock is
   exactly the situation worth surfacing.
2. **Reports the sync state** via `scripts/status.py` — a stdlib-only read of
   `.rhiza/template.lock`: the template repository and ref, the synced commit SHA and
   timestamp, the strategy, and the materialized paths.

Both scripts are stdlib-only, so this works without the `rhiza` CLI and without
PyYAML.

## Options

- `--json` — a machine-readable object. Its `files` array is always present, so it
  doesn't combine usefully with `--files`.
- `--files` (alias `--tree`) — append the managed files as a directory tree; the view
  the retired `/rhiza:tree` gave.
- `--check` — compare the pinned ref against the latest upstream release and print
  whether you're up to date or N releases behind.

## Notes

- **`--check` is the only option that needs network** — `git ls-remote --tags`, no
  `gh` and no auth for public repos. A git or network failure is reported, not fatal.
- Two states that look like failures but aren't: **no `template.lock`** means
  configured but never synced, and **`--check` reporting "behind"** is normal. Both
  point at [`/rhiza:update`](update.md), which performs the sync.
- **No `template.yml` at all** means the repo isn't rhiza-managed — that points at
  [`/rhiza:init`](init.md).
- For an assessment rather than a report, use [`/rhiza:quality`](quality.md).

<!-- generated:begin — rendered by scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `commands/status.md` |
| **Invocation** | `/rhiza:status [path to a repo root]  (optional; defaults to the current repo)` |
| **Model-invocable** | yes |
| **Allowed tools** | `Bash(uv*)`, `Read` |

<!-- generated:end -->
