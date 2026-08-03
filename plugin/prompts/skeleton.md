# Skeleton (internal procedure)

> **Not a slash command.** This file lives in `prompts/`, not `commands/`, so the
> user cannot invoke it. `/rhiza:init` reads it and follows it at its step 5b. If you
> are reading this because `/init` sent you here, carry on — you already have
> `OWNER`, `NAME`, and the host from `/init`'s step 2, so don't re-ask for them.

**Why this procedure exists.** The rhiza template never ships a project manifest —
the sync delivers `Makefile`, `.rhiza/rhiza.mk`, `ruff.toml`, `pytest.ini`, CI and
the rest, but the project metadata is always the repo's own. So `/update`'s gates
can't run at all without one: `make test` depends on `install` (a `uv sync`), and
the synced `.rhiza/tests/test_pyproject.py` asserts a specific `[project]` shape.
This produces that shape.

**It is a thin wrapper around `uv init --lib` plus the bundled
`plugin/scripts/init_skeleton.py`.** `uv` creates the skeleton; the deterministic,
stdlib-only script finishes it. Every edit is **idempotent and additive** — running
it twice changes nothing the second time, and it never overwrites real code or
metadata a human wrote.

**Three languages.** Steps 1–7 below are the **python** path. `/init` passes the language
in: for `LANGUAGE=rust` jump to **[Rust](#rust)**, the same shape with `cargo init --lib`
and `Cargo.toml` in place of uv and `pyproject.toml`; for `LANGUAGE=go` jump to
**[Go](#go)**, which is shorter than either, because `go mod init` writes one file and
`go.mod` has no metadata to fill in.

The project name is `NAME` — whatever `/init` settled, else `basename "$PWD"`.

## 1. Settle the inputs

- **`uv`** — `/init` has already followed `plugin/prompts/install-uv.md` by the time you get
  here, so `uv` is present. If `uv --version` somehow fails, `Read`
  `${CLAUDE_PLUGIN_ROOT}/prompts/install-uv.md` and follow it, then stop if it still
  fails.
- **Owner / repo** — use what `/init` passed you. Failing that, derive from
  `git remote get-url origin` without asking when
  there is one (`OWNER`, `REPO`, and the host → `github`/`gitlab`). Otherwise ask
  (`AskUserQuestion`); default `REPO` to `NAME`. These become the
  `[project.urls]` Homepage and Repository.
- **Python version** — only needed when there's no `pyproject.toml` yet (it pins
  `uv init --python`). Ask (`AskUserQuestion`) offering **3.11**, **3.12**, **3.13**,
  **3.14** — the floor is 3.11, never offer 3.9/3.10. Hold as `PYTHON_VERSION`. When
  a `pyproject.toml` already exists, read its `requires-python` instead of asking.
- **Description** — a sentence or two on what the project does, for
  `[project].description`. Ask; there's **no safe default** and the template's gate
  requires a non-empty one, so don't invent it. Skip the question when the existing
  `pyproject.toml` already has a real description (i.e. not uv's
  `Add your description here`). Hold as `DESCRIPTION`.

## 2. Create the skeleton (only when it's missing)

If there is **no** `pyproject.toml`:
```bash
uv init --lib --name "$NAME" --python "$PYTHON_VERSION"
```
This writes `pyproject.toml`, `src/<pkg>/__init__.py` (+ `py.typed`), `README.md`,
`.gitignore`, and `.python-version`, and initialises a git repo if there isn't one.

If a `pyproject.toml` **already exists**, do **not** run `uv init` — it refuses, and
the existing metadata is the user's. Go straight to step 3, which is safe to run on
a mature repo.

## 3. Finish it into a rhiza shape

Invoke the bundled script with the plugin-root path (`${CLAUDE_PLUGIN_ROOT}` resolves
at runtime — **keep the quotes**; in a source checkout it's empty, so fall back to
the repo-relative `plugin/scripts/init_skeleton.py`):
```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/init_skeleton.py" . \
  --owner "$OWNER" --repo "$REPO" --host <github|gitlab> \
  --description "$DESCRIPTION"
```
It makes four idempotent edits:
- **`src/<pkg>/__init__.py`** — replaces uv's `hello()` placeholder with a package
  docstring. It's undocumented and untested, so it fails *both* the interrogate gate
  and the coverage gate. Rewritten **only while it's still uv's placeholder** — once
  there's real code in it, the script leaves it alone.
- **`[project].description`** — replaces uv's placeholder; a real description is
  left untouched.
- **`[project.urls]`** — adds the `Homepage` and `Repository` entries the gate
  requires. Existing entries win; only missing keys are added.
- **`[dependency-groups]`** — adds the required `test` (with `pytest`) and `lint`
  groups, each lower-bounded, when absent. Existing groups are left exactly as they
  are.

Relay its `modified`/`notes` output.

## 4. Verify `pyproject.toml` exists — this is the gate

**Do not continue on trust.** The whole point of this procedure is that a
`pyproject.toml` exists afterwards, so assert it explicitly:
```bash
test -f pyproject.toml && head -20 pyproject.toml
```
- **It's there** — confirm it has a `[project]` table with a `name`, a non-empty
  `description`, `[project.urls]`, and `[dependency-groups]`. Those are exactly what
  the template's gate checks; the script writes them, so a missing one means
  something went wrong and is worth reporting.
- **It's absent** — **stop and report.** The script also exits **1** with a note in
  this case. It means `uv init --lib` never ran or failed silently, and everything
  downstream is broken: `/update`'s `make test` depends on `install` (a `uv sync`)
  that cannot resolve without it. Do **not** hand-write a `pyproject.toml` to paper
  over it, and do **not** let `/init` proceed to commit and open a PR — say plainly
  that the skeleton step failed and why.

## 5. Declare where the version lives, for `/rhiza:release`

**Step 3's script already did this** — `init_skeleton.py` appends a `[tool.bumpversion]`
table to `pyproject.toml`, anchored to `[project].version`, and says so in its notes
(`declared the version location in …`). Nothing to write by hand. What is left is to
*check*, because the consequence of it being absent is silent:

```bash
grep -l 'tool.bumpversion' .bumpversion.toml .bumpversion.cfg setup.cfg pyproject.toml 2>/dev/null
```

`/release` refuses to guess which files state the version, and `bump-my-version` itself
falls back to `git describe` without warning — so a missing table means a release can be
cut at a version that already exists. The table must live in a file the tool actually
searches (`.bumpversion.toml`, `.bumpversion.cfg`, `setup.cfg`, `pyproject.toml`); one
in `.rhiza/.cfg.toml` is never found, and the template's own
`test_a_discoverable_config_exists` gate fails on exactly that.

If the script reported that it wrote nothing because the manifest declares no version,
**stop** — that is step 4's gate failing, not something to paper over. If a
`[tool.bumpversion]` was already there, it is the user's and wins.

**A repo whose CI stubs point at itself** needs one entry per stub as well, or a
published tag ships workflows calling the previous version's reusable workflows. That
applies to a template repo, not to a downstream one, so only add it if you can see such
a self-reference in `.github/`.

## 6. Delegate the Python metadata

`Read` **`${CLAUDE_PLUGIN_ROOT}/prompts/python-version.md`** and follow it with
`$PYTHON_VERSION` (in a source checkout, `plugin/prompts/python-version.md`). It pins
`requires-python`, rewrites the `Programming Language :: Python :: X.Y` classifiers
to the supported range, and syncs `.python-version`. That's its job, so don't
hand-edit those fields here.

**The license is not this procedure's job either.** `plugin/prompts/license.md` owns the
SPDX metadata and the `LICENSE` file, and `/init` follows it right after this one.

## 7. Report

What happened, concisely: whether `uv init` ran or an existing `pyproject.toml` was
kept, the package directory under `src/`, which `pyproject.toml` fields the script
added or filled in (and which it found already correct), **that `pyproject.toml`
verified in step 4**, and the `$PYTHON_VERSION` applied. Flag anything the script
noted as still missing — notably `[project].authors`, which the template's gate wants
and which `uv init` only populates from `git config`.

## Rust

The python path above, with cargo in uv's place. Everything general still holds — the
edits are idempotent and additive, the license is `plugin/prompts/license.md`'s job, and the
gate in step 4 is not optional.

### R1. Settle the inputs

- **`cargo`** — `cargo --version`. If absent, tell the user to install the toolchain
  via [rustup](https://rustup.rs) (`curl --proto '=https' --tlsv1.2 -sSf
  https://sh.rustup.rs | sh`) and **stop** — don't try to install a toolchain for
  them, and don't fake a `Cargo.toml` without one.
- **Owner / repo** — exactly as step 1: use what `/init` passed, else derive from
  `git remote get-url origin`, else ask. These become `[package].repository` and
  `[package].homepage`.
- **Description** — as step 1. Ask; no safe default. Skip when `[package].description`
  already has a real value. Hold as `DESCRIPTION`.
- **No Rust-version question.** The edition comes from `cargo init`, and an MSRV
  (`[package].rust-version`) is a real constraint on downstream consumers — leave it
  unset rather than inventing one.

### R2. Create the skeleton (only when it's missing)

If there is **no** `Cargo.toml`:
```bash
cargo init --lib --name "$NAME"
```
This writes `Cargo.toml`, `src/lib.rs` (a placeholder `add` plus its test), and
`.gitignore`, and initialises a git repo if there isn't one. If a `Cargo.toml`
**already exists**, do **not** run `cargo init` — it refuses, and the existing
manifest is the user's.

### R3. Finish it into a rhiza shape

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/init_skeleton.py" . \
  --owner "$OWNER" --repo "$REPO" --host <github|gitlab> --language rust \
  --description "$DESCRIPTION"
```
(The script is stdlib-only Python — `uv` here is just how the plugin runs its own
tooling. It has nothing to do with the project being a Rust one.)

Three idempotent edits:
- **`src/lib.rs`** (or `main.rs`) — **prepends** a `//!` crate doc comment when there
  is none. `#![warn(missing_docs)]` fires on an undocumented crate root, and `cargo
  init` writes no docs. Unlike the python path this never *replaces* the placeholder:
  cargo's stub carries the project's only test.
- **`README.md`** — cargo creates no README at all, so this writes a stub.
  `/rhiza:docs` owns the real one and this never overwrites a non-empty file.
- **`[package]`** — adds `description`, `repository`, `homepage` and `authors` when
  absent, appended below `name`/`version`/`edition` where cargo put them. A value
  already in the manifest wins.

Relay its `modified`/`notes` output.

### R4. Verify `Cargo.toml` exists — this is the gate

```bash
test -f Cargo.toml && cargo metadata --no-deps --format-version 1 >/dev/null && head -20 Cargo.toml
```
`cargo metadata` is the real check — it parses the manifest and fails loudly on a
malformed one, which `test -f` cannot. If either fails, **stop and report**; do not
hand-write a `Cargo.toml`, and do not let `/init` commit or open a PR.

A **virtual workspace root** (`[workspace]` and no `[package]`) is the one case where
the script exits 1 legitimately: there's no package table to fill in. Say so, and
apply this procedure to the member crate instead.

### R5. Declare where the version lives, for `/rhiza:release`

**R3's script already did this**, as on the python side — but to `.bumpversion.toml`,
because Cargo has no `[tool]` table convention and `bump-my-version` does not read
`Cargo.toml`. It writes two file entries: `Cargo.toml` anchored to `[package]`, and
`Cargo.lock` anchored to the package's own name.

Check it exists and move on:

```bash
test -f .bumpversion.toml && grep -c 'tool.bumpversion' .bumpversion.toml
```

**Both entries matter, for different reasons.** The `[package]` anchor keeps the rewrite
off every dependency in `Cargo.lock` that happens to share the version number. And
`Cargo.lock` records the crate's *own* version, so bumping only `Cargo.toml` leaves the
lockfile stale and the next `cargo build` dirties the tree — which is why the lock entry
is there, and why it is `regex = true`: without that, its `\n` is matched literally, the
entry silently does nothing, and the release looks clean while the lockfile is wrong.

### R6. Report

As step 7: whether `cargo init` ran or an existing manifest was kept, which
`[package]` keys were added or found correct, **that `cargo metadata` passed in R4**,
and that no MSRV was set.

## Go

The shortest of the three, and short for a reason: `go mod init` writes exactly one file,
and `go.mod` holds a module path and a Go version — **no description, repository,
homepage, author or licence field exists in the format**. There is no manifest-filling
step here because there is nothing to fill. Everything general still holds: the edits are
idempotent and additive, the licence is `plugin/prompts/license.md`'s job, and the gate in G4 is
not optional.

### G1. Settle the inputs

- **`go`** — `go version`. If absent, tell the user to install a toolchain
  ([go.dev/dl](https://go.dev/dl/), or `brew install go`) and **stop** — don't install
  one for them, and don't hand-write a `go.mod` without one.
- **`MODULE` — the module path, and the one genuinely new question.** Python and Rust
  take a bare name; a Go module is identified by the path people will `go get`, so it
  must match where the repo lives: `github.com/$OWNER/$NAME` (or `gitlab.com/…`). Derive
  it from `git remote get-url origin` when there is one, else from `OWNER`/`NAME` and the
  host `/init` settled. **Ask only if none of that is available** — and never invent a
  vanity domain.
- **Description** — as step 1. Ask; no safe default. Hold as `DESCRIPTION`.
- **No Go-version question.** `go mod init` writes the toolchain's own version into the
  `go` directive, and raising it is a real constraint on consumers. Leave it.

### G2. Create the skeleton (only when it's missing)

If there is **no** `go.mod`:
```bash
go mod init "$MODULE"
```
That is the whole of it — one file, no `src/`, no starter package, no `.gitignore`. If a
`go.mod` **already exists**, do **not** run `go mod init`: it refuses, and the existing
module path is the user's.

### G3. Finish it into a rhiza shape

```bash
uv run --python 3.12 --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/init_skeleton.py" . \
  --owner "$OWNER" --repo "$REPO" --host <github|gitlab> --language go \
  --description "$DESCRIPTION"
```
(The script is stdlib-only Python — `uv` here is just how the plugin runs its own
tooling, exactly as on the Rust path. It has nothing to do with the project being Go.)

Two idempotent edits:
- **`doc.go`** — the package comment. `make docs-coverage` is revive's `exported` rule,
  Go's analogue of `#![warn(missing_docs)]` and of interrogate, and it wants one; `go mod
  init` leaves the module with no Go file at all, so `go test ./...` has nothing to run
  either. Written **only into a module with no root `.go` file**: a second package
  comment where one already exists is itself a lint finding.
- **`README.md`** — go creates none, so this writes a stub. `/rhiza:docs` owns the real
  one, and this never overwrites a non-empty file.

Relay its `modified`/`notes` output.

### G4. Verify `go.mod` exists — this is the gate

```bash
test -f go.mod && go list -m && go vet ./...
```
`go list -m` prints the module path and fails on a malformed `go.mod`, which `test -f`
cannot; `go vet` proves the package the script wrote actually compiles. If any of them
fails, **stop and report** — don't hand-write a `go.mod`, and don't let `/init` commit or
open a PR.

### G5. The version location is *not* written here

Unlike python and rust, **nothing to do** — say so and move on. A Go module's version is
its git tag, so a fresh module has no version anywhere to anchor a config to, and
`go-core` owns the declaration: the sync delivers a root `.bumpversion.toml` (with no
`current_version` key, deliberately) plus the `internal/version/version.go` constant a
built binary reports. Writing our own would be overwritten by that first `/rhiza:update`.

Tell the user the consequence, because it is surprising: **`/rhiza:release` will not work
until after the first `/update`**, and its first run has no tag to derive a version from,
so it starts from `0.0.0` — which `/release` handles, provided nobody hand-writes a
competing config in the meantime.

### G6. Report

As step 7: whether `go mod init` ran or an existing module was kept, the module path,
whether `doc.go` and the README were written or already present, **that `go list -m` and
`go vet` passed in G4**, and that the version location arrives with the first sync.

## Notes

- **Dependency lower bounds.** Any dependency added to `pyproject.toml` must carry
  one — `httpx>=0.27`, never a bare `httpx`. Prefer `uv add <pkg>` (it writes a `>=`
  bound); if you hand-edit `[project].dependencies`, add the bound yourself. This
  applies to optional and dependency-group entries too.
- **No license classifiers — ever.** Neither this procedure nor `plugin/prompts/license.md`
  writes a `License :: …` trove classifier: PEP 639 replaced it with the SPDX
  `license` field, which is what the license step sets. The template's
  `test_pyproject.py` still
  asserts one, so that check can fail — it lives in `make rhiza-tests`, not
  `make test`, so it doesn't block the main suite. **Do not add a `License ::`
  classifier to silence it.** Report the failure as an upstream template question
  instead; writing a deprecated classifier to satisfy a stale assertion is the wrong
  fix. The only classifiers that get written here are the
  `Programming Language :: Python :: X.Y` entries from step 6.
