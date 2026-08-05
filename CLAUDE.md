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
  locally owned. When you read that rule in `plugin/prompts/scorecard.md`, you're reading a
  rule *this repo ships for other repos*, not one that governs it.

## Commands

```bash
make help           # list every target
make lint           # all prek hooks over every file
make test           # pytest over tests/, 100% coverage gate on scripts/
make e2e            # only the end-to-end tests, no coverage gate (template-drift's target)
make mutate         # mutation-test the sync core (slow, scheduled — not in `make test`)
make book           # build the docs site into _book/ (runs paper + test first)
make book-serve     # docs with live reload
make paper          # build the LaTeX paper (needs tectonic or pdflatex)
make paper-figures  # regenerate the paper's figures
make clean          # drop caches and build artifacts
make changelog      # regenerate CHANGELOG.md from conventional commits
make install        # install the plugin via the claude CLI
```

**Prefer a bare `make <target>`.** Don't pipe, redirect, chain, or `cd`-prefix it, and
don't reach past it to the underlying tool. The plugin's own `PreToolUse` hook
(`plugin/hooks/hooks.json` → `plugin/scripts/hook_bash_guard.py`) denies a compound `make` and tells
you to re-run bare — the arguments, thresholds and exclusions
live in the target and in `.pre-commit-config.yaml`, so a direct `uvx ruff`/`uvx
interrogate` invocation measures something else. CI runs these same targets.

To run one hook instead of all of them: `uvx prek run <hook-id> --all-files`
(`mypy`, `interrogate`, `test-layout`, `command-contracts`, `prompt-wiring`,
`manifest-version-parity`).

**The hook runner here is [`prek`](https://prek.j178.dev/), not `pre-commit`.** The
config file keeps its `.pre-commit-config.yaml` name and schema — prek reads that format
unchanged — so the only places the choice is visible are `make lint` and the CI `lint`
job. Reach for `uvx prek update` rather than `pre-commit autoupdate` when bumping hook
revs — as with every other tool here, `uvx` fetches it, so nothing is installed globally.
Note that rhiza-*managed* repos are a different question: the template drives
`pre-commit`, which is why the prose under `plugin/` still says so.

`make lint && make test` green locally means a green PR. `make book` additionally needs
a LaTeX engine, so skip it for prose- or script-only changes.

## Architecture

The plugin is **two kinds of markdown plus the Python they drive**.

**The shipped plugin is `plugin/`. The repo that builds it is everything else.**
`.claude-plugin/marketplace.json` stays at the root and points inward with
`"source": "./plugin"`. The four directories inside `plugin/` are mandated by the plugin
spec, which requires `commands/`, `hooks/`, `prompts/` and `scripts/` at the *plugin*
root — so that grouping is not a choice you can tidy further.

| Path | What it is |
| --- | --- |
| `plugin/commands/*.md` | The eight slash commands users invoke, namespaced `/rhiza:<name>`. |
| `plugin/prompts/*.md` | Eight **internal procedures** commands reach with `Read`. |
| `plugin/hooks/hooks.json` | A `PreToolUse` hook on `Bash`, auto-discovered from the plugin root. |
| `plugin/scripts/*.py` | Bundled, stdlib-only Python the prose calls. |
| `plugin/.claude-plugin/plugin.json` | The plugin manifest. |
| `tests/scripts/*.py` | Pytest suite mirroring `plugin/scripts/` 1:1. Not shipped. |
| `docs/` | The MkDocs site: `commands/`, `internals/`, `index.md`, `development.md`. |
| `paper/` | A LaTeX introduction, rebuilt by CI and published with the site. |
| `.claude-plugin/marketplace.json` | The marketplace catalogue. |

**`${CLAUDE_PLUGIN_ROOT}` resolves to `plugin/`**, so every
`"${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py"` in the prose is unaffected by the layout.
Only the *source-checkout fallback* carries the prefix now — `plugin/scripts/<name>.py`.
`plugin/scripts/_rhiza_layout.py` holds the one definition of where things live; the
three checkers that span both halves import it rather than hardcoding `plugin/`.

**`commands/` vs `prompts/` is the load-bearing distinction.** Procedures live outside
`commands/` *specifically* so they cannot be invoked as slash commands — that's the
guarantee, not an organisational preference. `plugin/scripts/check_prompt_wiring.py` enforces
five rules about it: each procedure declares it isn't a slash command, carries no
command frontmatter, never collides with a command name, is actually referenced
somewhere, and is never invoked as a command. Don't "tidy" a procedure into
`commands/`.

Shared behaviour lives in the procedures, which is why `/init` and `/update` behave
identically where they overlap. `plugin/commands/init.md` alone does not explain `/rhiza:init`.

**The design split:** deterministic work belongs in tested Python; judgement belongs in
markdown. Parsing a lock file, merging synced files, comparing versions, drawing a
random song — those are scripts. Reading a repo and scoring it is prose.

**An underscore prefix means "not an entry point".** A command invokes
`scripts/<name>.py`; everything a script leans on lives in a `_`-prefixed sibling that no
command ever names. Three families, plus the sync core:

| Prefix | Owns |
| --- | --- |
| `_rhiza_*` | the sync core, and anything shared across unrelated commands — `_rhiza_toml` (add a TOML key, reformat nothing) serves the skeleton, `set_license` **and** `set_python_version`; `_rhiza_yaml` is the read/write façade over `_rhiza_yaml_parse` |
| `_skeleton_*` | one module per language behind `init_skeleton.py`, which is only the dispatcher and the CLI — each language's gap differs in kind, not degree |
| `_validate_*` | `validate.py`'s three halves: the `Log` sink, the language structure checks, the `template.yml` field checks |

Two consequences worth knowing before you move code. **The size and complexity bars are
enforced by measurement, not taste** — no module over 500 lines, no block above
cyclomatic C(12), every maintainability index ≥ 40 (`uvx radon cc plugin/scripts -s -n C`,
`uvx radon mi plugin/scripts -s`). And the 1:1 test-layout rule binds these modules too,
so extracting one is never a one-file change: it needs its own `test__<name>.py`.

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
2. Script-backed? Logic in `scripts/<name>.py`, tests in `tests/scripts/test_<name>.py`.
3. Add `docs/commands/<name>.md` **and** an `mkdocs.yml` `nav` entry. Write the prose
   only — run `plugin/scripts/render_command_docs.py` for the **Reference** block, which is
   generated from the frontmatter and gated by `docs-reference-blocks`.
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
- **The end-to-end tests are part of `make test`, not an opt-in extra.** `make e2e` exists,
  but it is a *narrowing* for the weekly template-drift job, which needs them without the
  coverage gate — not a flag that turns them on. Every `make test` runs them. They sync real
  repos from `jebel-quant/rhiza` at the ref pinned in `tests/conftest.py`, so the suite
  needs network, `uv`, and `cargo`/`go` for the Rust and Go fixtures. Anything tool-shaped
  skips when the tool is absent, which is why CI verifies both toolchains explicitly
  rather than letting a whole language axis vanish quietly.
- **The suite carries no `xfail` and no tolerated upstream failure, and both emptied
  themselves.** `test_e2e_the_test_gate_of_a_fresh_repo_collects_something` asserts that a
  repo straight out of `/init` + `/update` has a test its `make test` can collect. Rust
  gets one from `cargo init`, Go one from `go-core`, and Python — which had none — got a
  `test_rhiza_packaging.py` under its own `tests/` in **v1.3.2**, so the `xfail(strict=True)`
  that had held the Python case turned XPASS at the ref bump and went. `_UPSTREAM_KNOWN_FAILURES` in
  `test_check_make_targets.py` emptied the same way. Keep both at zero: each is
  self-retiring by design, so an entry that stops being needed turns the suite **red**, and
  the fix is deleting the entry, never the assertion. Note the fixture pairing the test
  rests on — `python_synced_repo` is unseeded, `synced_repo` hand-writes a module and
  would hide it.
- **The pinned template ref decides which profiles the suite can exercise.**
  `rust-local` and `go-local` arrived in rhiza **v1.3.0**, so `PINNED_TEMPLATE_REF` names
  that release or later (**v1.3.2** today) — which is why both syncs run on every PR
  instead of skipping for want of a released profile. Before bumping it, check
  the new ref still defines what `/init` writes: `plugin/scripts/check_template_profile.py
  rust-local go-local github-project gitlab-project --template-repo jebel-quant/rhiza
  --ref <tag>`. A ref that doesn't now **fails** those fixtures rather than skipping them
  — see `require_language_profile`.
- **One template, three languages.** `jebel-quant/rhiza` is the default for python, rust
  and go alike; the language selects the *profile* (`github-project`, `rust-local`,
  `go-local`), never a different repository.
