# Design analysis (internal procedure)

> **Not a slash command.** This file lives in `prompts/`, which Claude Code does not
> scan for commands, so the user cannot invoke it. `/rhiza:quality` reads it and follows it after the gates.

Complexity and architecture are **not measured by any `make` gate**, so unlike every
other input to the scorecard, this evidence has to be gathered by hand. That is the
whole reason this procedure exists: without it, the two subcategories `/quality` is
required to always score would be guesses.

**Scope: the repo's locally-owned source only.** Skip Rhiza-managed files — see the
scoping rule in `plugin/prompts/scorecard.md`. A synced file's complexity is upstream's problem.

**Gather, don't judge.** Produce evidence and let `plugin/prompts/scorecard.md` turn it into
marks. Every claim must name what you actually read or ran; if a number is unavailable,
say so rather than estimating silently.

## 0. Which language, and therefore which tools

`radon` is a Python tool and `src/` is a Python layout. Neither is a safe default: on a
Go or Rust repo they produce nothing, and "nothing" reported as a low mark is the same
category error as scoring an unsynced repo as broken. Ask first (**keep the quotes**;
in a source checkout use the repo-relative path):

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/language_profile.py" --json
```

It returns the language, the **source root** to point the tools at, and the
`complexity` and `graph` commands for that ecosystem. Use those rather than the ones
written below — the block in §1 is the Python case spelled out, not the only case.

Exit **1** means the language could not be determined. Say so and gather what you can
by reading the code; do not fall back to the Python tooling on a repo that isn't
Python.

**The tools may not be installed.** `radon`, `gocyclo` and `clippy` are all optional in
their own ecosystems. An absent tool is the "unavailable" case below, never a finding
against the repo.

## 1. Complexity

The Python case, as an example of the shape — substitute the `complexity` commands
`language_profile.py` returned, and `source_root` for `src`:

```bash
uvx radon cc src -a -s     # per-block cyclomatic complexity + average
uvx radon mi src -s        # maintainability index
find src -name '*.py' | xargs wc -l | sort -rn
```

For Go that is `gocyclo -avg -over 15 .` and `go vet ./...`; for Rust,
`cargo clippy --all-targets -- -W clippy::cognitive_complexity`. These report different
things — Go and Rust give you per-function complexity and lint findings but no
maintainability index, so **report what the tool actually measured** and mark the rest
unavailable rather than substituting a proxy.

Report:

- every block ranking **C or worse (CC ≥ 11)**, as `file:line`;
- any module below **A** on the maintainability index;
- the largest modules and functions, with line counts.

If the complexity tool is unavailable, read the largest modules and estimate by
inspection — and **say that you did**. An estimate presented as a measurement is worse
than no number.

## 2. Architecture

Map the dependency graph with the `graph` commands `language_profile.py` returned
(`go mod graph` / `go list -deps ./...` for Go, `cargo tree --edges normal` for Rust,
import scanning for Python), then check four things. The four questions are
language-neutral even though the tooling isn't — packages, crates and modules all have
layers, cycles and hotspots:

- **Layering direction.** A lower layer must not import an upper one — `models/`
  importing `commands/` or `cli` is a violation. Name the offending import.
- **Import cycles — including ones hidden behind deferred (function-local) imports.**
  A module-level cycle usually crashes and gets fixed; a function-local one survives
  for years and is the more common finding. Grep inside function bodies, don't just
  read the top of each file. (Go rejects package import cycles at compile time, so
  there the equivalent finding is a cycle smuggled through an interface or an
  `internal/` package doing two jobs; Rust allows module cycles freely.)
- **Module responsibility.** Application or orchestration logic living in a model or
  utility layer; god-modules imported by many; modules doing two unrelated jobs.
- **Coupling hotspots** — a module imported by many, or one importing many — and the
  **composition pattern** in use (mixins, Protocols, dependency injection).

## 3. The other judgement-based criteria

`plugin/prompts/scorecard.md` lists subcategories that no gate measures either — test design
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
