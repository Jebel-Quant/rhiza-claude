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
`scripts/init_skeleton.py`.** `uv` creates the skeleton; the deterministic,
stdlib-only script finishes it. Every edit is **idempotent and additive** — running
it twice changes nothing the second time, and it never overwrites real code or
metadata a human wrote.

**Two languages.** Steps 1–7 below are the **python** path. For `LANGUAGE=rust`,
`/init` passes the language in — jump to **[Rust](#rust)** at the end, which is the
same shape with `cargo init --lib` and `Cargo.toml` in place of uv and
`pyproject.toml`. `go` doesn't come here at all.

The project name is `NAME` — whatever `/init` settled, else `basename "$PWD"`.

## 1. Settle the inputs

- **`uv`** — `/init` has already followed `prompts/install-uv.md` by the time you get
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
the repo-relative `scripts/init_skeleton.py`):
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

`/release` refuses to guess which files state the version — it reads
`[tool.bumpversion]`. Without it the first release stops dead, so add the config now
while the repo's shape is known. Append to `pyproject.toml` (or write
`.bumpversion.toml`) if no `[tool.bumpversion]` exists yet:

```toml
[tool.bumpversion]
current_version = "0.1.0"   # match [project].version
tag = false                 # /rhiza:release tags after the changelog lands
commit = false              # ... and commits, so the diff is reviewable first
allow_dirty = false         # a release is cut from a clean tree

[[tool.bumpversion.files]]
filename = "pyproject.toml"
regex = true
search = '(?ms)^\[project\]((?:(?!^\[)[\s\S])*?)^version = "{current_version}"'
replace = '[project]\1version = "{new_version}"'
```

**The pattern must be anchored.** `search`/`replace` apply to *every* occurrence in a
file, so the naive `search = 'version = "{current_version}"'` would also rewrite a
`[tool.something].version` that happens to share the number. The `regex` form above
confines the change to the `[project]` table. (Dependency pins like `httpx>=0.27` are
never at risk — they aren't line-anchored `version = ` assignments.)

Set `current_version` to whatever `[project].version` actually says — they must agree,
or `bump-my-version` won't find its search pattern.

**A repo whose CI stubs point at itself** needs one entry per stub as well, or a
published tag ships workflows calling the previous version's reusable workflows. That
applies to a template repo, not to a downstream one, so only add it if you can see such
a self-reference in `.github/`.

## 6. Delegate the Python metadata

`Read` **`${CLAUDE_PLUGIN_ROOT}/prompts/python-version.md`** and follow it with
`$PYTHON_VERSION` (in a source checkout, `prompts/python-version.md`). It pins
`requires-python`, rewrites the `Programming Language :: Python :: X.Y` classifiers
to the supported range, and syncs `.python-version`. That's its job, so don't
hand-edit those fields here.

**The license is not this procedure's job either.** `prompts/license.md` owns the
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
edits are idempotent and additive, the license is `prompts/license.md`'s job, and the
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

Same rule as step 5 — `/release` reads `[tool.bumpversion]` and refuses to guess.
Rust has no `[tool]` table convention, so write **`.bumpversion.toml`**:

```toml
[tool.bumpversion]
current_version = "0.1.0"   # match [package].version
tag = false
commit = false
allow_dirty = false

[[tool.bumpversion.files]]
filename = "Cargo.toml"
regex = true
search = '(?ms)^\[package\]((?:(?!^\[)[\s\S])*?)^version = "{current_version}"'
replace = '[package]\1version = "{new_version}"'

[[tool.bumpversion.files]]
filename = "Cargo.lock"
search = 'name = "{name}"\nversion = "{current_version}"'
ignore_missing_file = true
```

**The `[package]` anchor matters more here than in python.** An unanchored
`version = "{current_version}"` would rewrite every dependency in `Cargo.lock` that
happens to share the number. And `Cargo.lock` records the crate's own version, so a
release that bumps only `Cargo.toml` leaves the lockfile stale and the next `cargo
build` dirties the tree — hence the second entry (`{name}` is the crate name; fill it
in literally).

### R6. Report

As step 7: whether `cargo init` ran or an existing manifest was kept, which
`[package]` keys were added or found correct, **that `cargo metadata` passed in R4**,
and that no MSRV was set.

## Notes

- **Dependency lower bounds.** Any dependency added to `pyproject.toml` must carry
  one — `httpx>=0.27`, never a bare `httpx`. Prefer `uv add <pkg>` (it writes a `>=`
  bound); if you hand-edit `[project].dependencies`, add the bound yourself. This
  applies to optional and dependency-group entries too.
- **No license classifiers — ever.** Neither this procedure nor `prompts/license.md`
  writes a `License :: …` trove classifier: PEP 639 replaced it with the SPDX
  `license` field, which is what the license step sets. The template's
  `test_pyproject.py` still
  asserts one, so that check can fail — it lives in `make rhiza-tests`, not
  `make test`, so it doesn't block the main suite. **Do not add a `License ::`
  classifier to silence it.** Report the failure as an upstream template question
  instead; writing a deprecated classifier to satisfy a stale assertion is the wrong
  fix. The only classifiers that get written here are the
  `Programming Language :: Python :: X.Y` entries from step 6.
