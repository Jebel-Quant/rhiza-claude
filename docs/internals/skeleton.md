# skeleton (internal)

Create the project skeleton a rhiza-managed repo needs — in Python, Rust or Go — and
finish it into the shape the template's gates require.

!!! note "Not a slash command"
    This is an **internal procedure** (`plugin/prompts/skeleton.md`), not something you
    invoke. [`/rhiza:init`](../commands/init.md) reads and follows it at its step 5b.

## Why it exists

**The rhiza template never ships a `pyproject.toml`.** The sync delivers the
`Makefile`, `.rhiza/rhiza.mk`, `ruff.toml`, `pytest.ini`, `.python-version` and CI —
but the project metadata is always the repo's own. So without one,
[`/rhiza:update`](../commands/update.md)'s gates can't run at all: `make test` depends on
`install` (a `uv sync`), and the synced `.rhiza/tests/test_pyproject.py` asserts a
specific `[project]` shape. This command produces that shape.

It's a thin wrapper around the language's own initialiser (`uv init --lib`,
`cargo init --lib`, `go mod init`) plus the bundled `plugin/scripts/init_skeleton.py`.
The steps below are the Python path; see [Rust and Go](#rust-and-go).

## What it does

1. **Settles the inputs** — runs [install-uv](install-uv.md) first, derives
   owner/repo from the `origin` remote when there is one, and asks for the
   **description** (the gate requires a non-empty one) and, on a fresh repo, the
   **Python version** (3.11–3.14).
2. **Runs `uv init --lib`** — only when there's no `pyproject.toml` yet. It writes
   `pyproject.toml`, `src/<pkg>/__init__.py` (+ `py.typed`), `README.md`,
   `.gitignore`, and `.python-version`, and initialises a git repo if needed. An
   existing `pyproject.toml` is never touched by `uv init`.
3. **Finishes it** via `plugin/scripts/init_skeleton.py` — four idempotent, additive edits:
   - **`src/<pkg>/__init__.py`** — replaces uv's `hello()` placeholder with a package
     docstring (it's undocumented *and* untested, so it fails both the interrogate
     and coverage gates). Rewritten **only while it's still uv's placeholder**.
   - **`[project].description`** — fills in uv's `Add your description here`; a real
     description is left alone.
   - **`[project.urls]`** — adds the required `Homepage` and `Repository`. Existing
     entries win.
   - **`[dependency-groups]`** — adds the required `test` (with `pytest`) and `lint`
     groups, lower-bounded, when absent. Existing groups are untouched.
4. **Delegates the Python metadata** to
   [python-version](python-version.md) — `requires-python`, the
   `Programming Language :: Python :: X.Y` classifiers, and `.python-version`.

The license is **not** its job: [license](license.md) owns that, and
[`/rhiza:init`](../commands/init.md) follows it immediately after this procedure.

## Rust and Go

Same shape, different manifest — and each has one thing the others don't:

| | Rust | Go |
| --- | --- | --- |
| initialiser | `cargo init --lib` | `go mod init <module path>` |
| manifest | `Cargo.toml` | `go.mod` |
| profile | `rust-local` | `go-local` |
| docs gate | `#![warn(missing_docs)]` — a `//!` crate doc is **prepended**, never substituted, because cargo's stub holds the crate's only test | revive's `exported` rule — a `doc.go` package comment, since `go mod init` writes no Go file at all |
| metadata | `[package]` gains `description`, `repository`, `homepage`, `authors` | **nothing to add**: `go.mod` has no such fields |
| version location | `.bumpversion.toml`, anchored to `[package]` and to `Cargo.lock` | **not written here** — a Go module's version is its git tag, and `go-core` ships the config; it arrives with the first [`/rhiza:update`](../commands/update.md) |

The gate is the same idea in each: `cargo metadata` (Rust) or `go list -m` plus
`go vet` (Go) must pass, or the procedure stops rather than hand-writing a manifest.

## Notes

- **Idempotent.** Run it twice and the second run changes nothing. Safe on a mature
  repo — it only fills gaps.
- **No license classifiers, ever.** Neither this command nor
  [license](license.md) writes a `License :: …` trove classifier — PEP 639
  replaced it with the SPDX `license` field. The template's `test_pyproject.py` still
  asserts one, so that check can fail; it runs under `make rhiza-tests`, not
  `make test`, so it doesn't block the main suite. It's reported as an upstream
  template question rather than papered over with a deprecated classifier. The only
  classifiers written are `/python-version`'s Python entries.
- **`[project].authors`** — the gate wants at least one, and `uv init` only populates
  it from your `git config`. The command flags it if it's missing.
- **Lower bounds** on every dependency (`httpx>=0.27`, never bare `httpx`), including
  optional and dependency-group entries.

<!-- generated:begin — rendered by plugin/scripts/render_command_docs.py; do not edit -->

## Reference

| | |
| --- | --- |
| **Source** | `plugin/prompts/skeleton.md` |
| **Invocation** | **not a slash command** — reached with `Read`, never invoked |
| **Read by** | [`/rhiza:init`](../commands/init.md), [`license`](license.md), [`python-version`](python-version.md) |

<!-- generated:end -->
