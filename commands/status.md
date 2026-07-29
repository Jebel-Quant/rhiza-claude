---
description: Report the repo's rhiza state — both halves of it. First validates the configuration via scripts/validate.py (that the target is a git repo with the expected language-specific structure, that `.rhiza/template.yml` exists and parses, and that its required/optional fields are present and well-typed), then reports what was actually synced from `.rhiza/template.lock` (template repository, ref, commit SHA, timestamp, strategy, managed files) via scripts/status.py. Intent versus outcome — the two can disagree, so reporting one alone misleads. Add --files to list the managed files as a tree, or --check to compare the pinned ref against the latest upstream release. Both scripts are stdlib-only, so this works without the rhiza CLI. Read-only; no scoring, no fixes, no issues. Absorbs what used to be /rhiza:validate.
argument-hint: "[path to a repo root]  (optional; defaults to the current repo)"
allowed-tools: Bash(uv*), Read
---

You are running `/status` in the **current working directory's repo**.

**A repo's rhiza state has two halves, and this reports both:**

| half | file | question |
| --- | --- | --- |
| **config** | `.rhiza/template.yml` + repo structure | is what we'd sync *from* well-formed? |
| **sync** | `.rhiza/template.lock` | what was actually synced, and when? |

They can disagree in both directions, which is why reporting one without the other
misleads: a freshly `/init`-ed repo has a valid config and **no lock at all**, and a
long-synced repo can have a lock alongside a config someone has since broken by hand.

**This command is a thin wrapper around two bundled scripts** —
`scripts/validate.py` and `scripts/status.py`, both deterministic and stdlib-only (no
`rhiza` CLI, no PyYAML). Do **not** re-implement the parsing or gather fields
yourself; run them and relay the output.

Purely descriptive: it **reports; it does not score, fix, or file anything**.

Argument (optional): `$ARGUMENTS` — a path to the repo root to inspect; default is
the current directory.

## 1. Validate the config

`${CLAUDE_PLUGIN_ROOT}` resolves at runtime (**keep the quotes**); in a source
checkout it's empty, so fall back to the repo-relative path.

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/validate.py" $ARGUMENTS
```

It checks more than the file: that the target is a git repo, that it has the expected
language-specific structure (a `pyproject.toml` is required for Python), that
`template.yml` exists and parses, and that its fields are present and well-typed. It
exits **non-zero on any of those failing** — that's its contract as a gate, so it stays
usable in CI. Here, treat a failure as a *finding to report*, not a reason to
stop: still run step 2, because a broken config alongside a good lock is exactly the
situation worth surfacing. Lead the report with the validation failure.

If there's no `template.yml` at all, the repo isn't rhiza-managed. Say so and point at
`/rhiza:init`; skip step 2.

## 2. Report the sync state

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" $ARGUMENTS
```

Flags, added only when the user asks for them:

- `--json` — machine-readable; the default is the human summary. (Its `files` array
  is always present, so `--json` and `--files` don't combine usefully.)
- `--files` (alias `--tree`) — list the managed files as a directory tree beneath the
  summary. This is the view the retired `/rhiza:tree` gave.
- `--check` — compare the pinned `ref` to the latest upstream release via
  `git ls-remote --tags` (no `gh`, no auth) and print an `Update` line, e.g.
  `v1.0.0 → v1.2.0 (2 releases behind) — run /update`, or `up to date`. **The only
  part of this command that touches the network**; a git or network failure is
  reported, never fatal.

## 3. If a script can't run

If `uv` is missing, or a script isn't found at either path, report that plainly and
stop — don't hand-roll the status or the validation as a substitute.

## 4. Relay the results

Show each script's output as-is; both are already formatted. Then, at most **one short
line** tying the two halves together — whether the config is sound and how fresh the
sync looks. **No scores, no recommendations.**

Two non-error states worth naming explicitly rather than reporting as failures:

- **`No template.lock found`** — the repo is configured but never synced. Point at
  `/update`, which performs the first sync.
- **Config valid, lock present, `--check` says behind** — normal; that's what
  `/update` is for.

For an assessment rather than a report, point the user at `/quality`.
