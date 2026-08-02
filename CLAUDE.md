# CLAUDE.md

Guidance for Claude Code sessions in **rhiza-claude** — the Claude Code plugin
marketplace providing the `rhiza` plugin.

## Read this first: which side of the boundary you're on

This repo **is the plugin**. It is *not* a rhiza-managed repo — there is no `.rhiza/`
directory, no `template.yml`, no `template.lock`, and nothing here is synced from
anywhere. That has two consequences worth internalising before you touch anything:

- **`/rhiza:quality` will not run here, and that is correct.** Its step-0 precondition
  is `.rhiza/template.yml` **and** `.rhiza/rhiza.mk`; both are absent. The gates below
  are this repo's own, not the template's.
- **The "locally-owned vs Rhiza-owned" scoping rule doesn't apply.** Every file here is
  locally owned. When you read that rule in `prompts/scorecard.md`, you're reading a
  rule *this repo ships for other repos*, not one that governs it.

## Commands

```bash
make help           # list every target
make lint           # all pre-commit hooks over every file
make test           # pytest over tests/, 100% coverage gate on scripts/
make book           # build the docs site into _book/ (runs paper + test first)
make book-serve     # docs with live reload
make paper          # build the LaTeX paper (needs tectonic or pdflatex)
make paper-figures  # regenerate the paper's figures
make clean          # drop caches and build artifacts
make changelog      # regenerate CHANGELOG.md from conventional commits
make install        # install the plugin via the claude CLI
```

**Prefer a bare `make <target>`.** Don't pipe, redirect, chain, or `cd`-prefix it, and
don't reach past it to the underlying tool — the arguments, thresholds and exclusions
live in the target and in `.pre-commit-config.yaml`, so a direct `uvx ruff`/`uvx
interrogate` invocation measures something else. CI runs these same targets.

To run one hook instead of all of them: `uvx pre-commit run <hook-id> --all-files`
(`mypy`, `interrogate`, `test-layout`, `command-contracts`, `prompt-wiring`,
`manifest-version-parity`).

`make lint && make test` green locally means a green PR. `make book` additionally needs
a LaTeX engine, so skip it for prose- or script-only changes.

## Architecture

The plugin is **two kinds of markdown plus the Python they drive**.

| Path | What it is |
| --- | --- |
| `commands/*.md` | The eight slash commands users invoke, namespaced `/rhiza:<name>`. |
| `prompts/*.md` | Seven **internal procedures** commands reach with `Read`. |
| `scripts/*.py` | Bundled, stdlib-only Python the prose calls. |
| `tests/*.py` | Pytest suite mirroring `scripts/` 1:1. |
| `docs/` | The MkDocs site: `commands/`, `internals/`, `index.md`, `development.md`. |
| `paper/` | A LaTeX introduction, rebuilt by CI and published with the site. |
| `.claude-plugin/` | `plugin.json` + `marketplace.json`. |

**`commands/` vs `prompts/` is the load-bearing distinction.** Procedures live outside
`commands/` *specifically* so they cannot be invoked as slash commands — that's the
guarantee, not an organisational preference. `scripts/check_prompt_wiring.py` enforces
five rules about it: each procedure declares it isn't a slash command, carries no
command frontmatter, never collides with a command name, is actually referenced
somewhere, and is never invoked as a command. Don't "tidy" a procedure into
`commands/`.

Shared behaviour lives in the procedures, which is why `/init` and `/update` behave
identically where they overlap. `commands/init.md` alone does not explain `/rhiza:init`.

**The design split:** deterministic work belongs in tested Python; judgement belongs in
markdown. Parsing a lock file, merging synced files, comparing versions, drawing a
random song — those are scripts. Reading a repo and scoring it is prose.

**Script path convention.** Commands invoke scripts as
`"${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py"` — keep the quotes. In a source checkout
that variable is empty, so prose should offer the repo-relative fallback.

## Conventions

**`scripts/` is held to a hard bar**, all of it gated in `.pre-commit-config.yaml`:

- **stdlib-only** — no third-party imports. The plugin must work with no install step.
- **`mypy` strict** and **100% `interrogate` docstring coverage**.
- **100% test coverage** — `make test` fails under 100%, so a new script is never a
  one-file change.
- **`tests/` mirrors `scripts/` 1:1** — `check_test_layout.py` requires `test_<name>.py`
  per module and a `Test<Class>` per source class, in both directions.

**The prose is gated too**, which is unusual and is the point:
`check_command_contracts.py` treats every command as a contract — the frontmatter
parses and declares `description`/`argument-hint`/`allowed-tools`, fenced `bash` blocks
pass `bash -n`, every `scripts/<name>.py` referenced exists, every `--flag` passed is
one that script's `argparse` accepts, every `/rhiza:<name>` resolves, and
`allowed-tools` covers the binaries the blocks run. A renamed flag breaks the build
rather than breaking in front of a user mid-task.

**When adding or changing a command:**

1. Edit `commands/<name>.md`; keep the frontmatter accurate.
2. Script-backed? Logic in `scripts/<name>.py`, tests in `tests/test_<name>.py`.
3. Add `docs/commands/<name>.md` **and** an `mkdocs.yml` `nav` entry. (Not yet gated —
   see issue #89.)
4. Update `README.md` if it's a headline command.

**Versioning.** The two manifests must agree; `manifest-version-parity` enforces it.
Both are declared in `.bumpversion.toml`, so `bump-my-version` writes them together —
`/rhiza:release` drives it. Never hand-edit a version.

**Commits** follow Conventional Commits; `CHANGELOG.md` is generated from them. Branch
off `main` and open a PR — never push to the default branch.

## Gotchas

- **`docs/reports/`, `docs/paper/`, `_book/`, `_tests/` are build outputs**, all
  gitignored. `make book` copies test reports into the site and renders the coverage
  badge *from the measured run*, so a published number can't be asserted by hand.
- **`markdownlint` excludes `commands/`** — those files are prompts, not docs. The repo
  root (this file included) is linted.
- **`make book` depends on `paper` and `test`** by design: the docs link the PDF and
  `mkdocs build --strict` fails on a missing target, so neither can silently go stale.
- **The end-to-end tests are part of `make test`, not an opt-in extra.** They sync real
  repos from `jebel-quant/rhiza` at the ref pinned in `tests/conftest.py`, so the suite
  needs network, `uv`, and `cargo`/`go` for the Rust and Go fixtures. Anything tool-shaped
  skips when the tool is absent, which is why CI verifies both toolchains explicitly
  rather than letting a whole language axis vanish quietly.
- **The pinned template ref decides which profiles the suite can exercise.**
  `rust-local` and `go-local` arrived in rhiza **v1.3.0**, which is what
  `PINNED_TEMPLATE_REF` names and why both syncs run on every PR. Before bumping it, check
  the new ref still defines what `/init` writes: `scripts/check_template_profile.py
  rust-local go-local github-project gitlab-project --template-repo jebel-quant/rhiza
  --ref <tag>`. A ref that doesn't now **fails** those fixtures rather than skipping them
  — see `require_language_profile`.
- **One template, three languages.** `jebel-quant/rhiza` is the default for python, rust
  and go alike; the language selects the *profile* (`github-project`, `rust-local`,
  `go-local`), never a different repository.
