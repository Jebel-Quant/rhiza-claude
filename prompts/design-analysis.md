# Design analysis (internal procedure)

> **Not a slash command.** This file lives in `prompts/`, not `commands/`, so the
> user cannot invoke it. `/rhiza:quality` reads it and follows it after the gates.

Complexity and architecture are **not measured by any `make` gate**, so unlike every
other input to the scorecard, this evidence has to be gathered by hand. That is the
whole reason this procedure exists: without it, the two subcategories `/quality` is
required to always score would be guesses.

**Scope: locally-owned `src/` only.** Skip Rhiza-managed files — see the scoping rule
in `prompts/scorecard.md`. A synced file's complexity is upstream's problem.

**Gather, don't judge.** Produce evidence and let `prompts/scorecard.md` turn it into
marks. Every claim must name what you actually read or ran; if a number is unavailable,
say so rather than estimating silently.

## 1. Complexity

```bash
uvx radon cc src -a -s     # per-block cyclomatic complexity + average
uvx radon mi src -s        # maintainability index
find src -name '*.py' | xargs wc -l | sort -rn
```

Report:

- every block ranking **C or worse (CC ≥ 11)**, as `file:line`;
- any module below **A** on the maintainability index;
- the largest modules and functions, with line counts.

If `radon` is unavailable, read the largest modules and estimate by inspection — and
**say that you did**. An estimate presented as a measurement is worse than no number.

## 2. Architecture

Map the import graph, then check four things:

- **Layering direction.** A lower layer must not import an upper one — `models/`
  importing `commands/` or `cli` is a violation. Name the offending import.
- **Import cycles — including ones hidden behind deferred (function-local) imports.**
  A module-level cycle usually crashes and gets fixed; a function-local one survives
  for years and is the more common finding. Grep inside function bodies, don't just
  read the top of each file.
- **Module responsibility.** Application or orchestration logic living in a model or
  utility layer; god-modules imported by many; modules doing two unrelated jobs.
- **Coupling hotspots** — a module imported by many, or one importing many — and the
  **composition pattern** in use (mixins, Protocols, dependency injection).

## 3. The other judgement-based criteria

`prompts/scorecard.md` lists subcategories that no gate measures either — test design
quality, error handling and CLI UX, security posture, semver discipline,
cross-platform robustness, idempotency, user-facing docs. Sample the code for each.

**Score only those with enough signal to justify a mark, and name the evidence you
read.** Silence is better than a mark invented to fill the table.

## 4. Hand back

Return, for the scorecard to consume:

- the complexity numbers (average CC, worst blocks as `file:line`, MI outliers,
  largest modules);
- the architecture findings (layering violations, cycles, hotspots, pattern);
- for each judgement-based criterion: either the evidence you read, or an explicit
  "insufficient signal".
