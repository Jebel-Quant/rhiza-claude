# scorecard (internal)

Turn gate results and design evidence into 1–10 marks, findings, and optionally issues.

!!! note "Not a slash command"
    This is an **internal procedure** (`prompts/scorecard.md`), not something you
    invoke. [`/rhiza:quality`](../commands/quality.md) reads and follows it once the
    gates have run and [design-analysis](design-analysis.md) has produced its evidence.

## The scoping rule

The most important rule in the plugin's scoring: **score only what the repo owns.**

- **In scope:** `src/`, `tests/`, `pyproject.toml`, `README.md`, project docs,
  `.rhiza/template.yml`, locally-hardened config.
- **Out of scope:** everything the template delivers — `.github/workflows/*`,
  `Makefile`, `.pre-commit-config.yaml`, `pytest.ini`, `ruff.toml`, and the
  typecheck/mutation/fuzzing targets.

A gap in a Rhiza-owned file is fixed **upstream**, and is reported as
"upstream/out-of-scope" rather than scored. Without this, every managed repo would be
marked down for its own template — making the score meaningless and identical
everywhere. A gate that was *unavailable* for the repo's profile is out-of-scope too,
never a FAIL.

## What it does

1. **Assigns marks** — always the two design subcategories, plus the gate-derived ones
   (lint, types, docs, test pass rate, coverage, deps/security, template fidelity) and
   any additional ones with real signal: test *design* quality, error handling and CLI
   UX, security posture, semver discipline, cross-platform robustness, idempotency,
   user-facing docs.
2. **Requires evidence per mark** — a score with a justification that cites nothing
   isn't earned; the subcategory is dropped instead.
3. **Produces findings** — one per subcategory below 10, each with a self-contained
   title, current→target score, the file(s)/lines to change, a `done when…` criterion,
   and an evidence snippet, ordered by leverage.
4. **Offers to file them** — via an `AskUserQuestion` multi-select, never free text.
   Nothing is created without an explicit selection. Filing goes through
   `scripts/platform_cli.py issue-create`, which maps to `gh issue create` or
   `glab issue create` — and matters because `glab issue create` has **no** body-file
   flag, so the body has to be passed inline.

## Notes

- **The coverage bar is the repo's own `COVERAGE_FAIL_UNDER`**, not a number picked at
  scoring time.
- **Coverage alone doesn't earn the test-design mark** — a brittle suite can hit 100%
  and still pin internals.
- It re-runs nothing and gathers nothing. A missing number means an unscored
  subcategory, not a guess.
