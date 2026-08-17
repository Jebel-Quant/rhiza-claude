# Development

The plugin's slash commands are Markdown prompt files under `skills/`; the
stdlib-only scripts they call live under `scripts/`, with tests under `tests/`.

## Layout

The repo separates **what ships** from **what builds it**: the plugin is `plugin/`,
everything else is tooling. `.claude-plugin/marketplace.json` stays at the root and
points inward with `"source": "./plugin"`.

| Path | Purpose |
| --- | --- |
| `.claude-plugin/marketplace.json` | Marketplace manifest. Root, because that's where `marketplace add` looks. |
| `plugin/.claude-plugin/plugin.json` | The `rhiza` plugin manifest. |
| `plugin/skills/` | The plugin's nine slash commands (`<name>/SKILL.md`). |
| `plugin/prompts/` | Internal procedures the commands `Read`. |
| `plugin/hooks/` | `hooks.json` — the `PreToolUse` hook that guards Bash calls at runtime. |
| `plugin/scripts/` | Bundled stdlib-only Python scripts backing the commands. |
| `tests/` | Pytest suite for the scripts. Not shipped. |
| `docs/` | This book. Not shipped. |
| `paper/` | The LaTeX introduction. Not shipped. |

**`skills/` and `hooks/` are the spec's; `prompts/` and `scripts/` are ours.**
Claude Code discovers components by looking for those two at the *plugin* root, so
those names are fixed; alongside them it also recognises `agents/`, `.mcp.json`,
`.lsp.json`, `monitors/`, `bin/` and `settings.json`, none of which this plugin ships.
`prompts/` and `scripts/` appear in no spec — `prompts/` is deliberately *not* a discovery
location, which is what stops a procedure being invocable as a slash command.

**Every command is a skill.** `plugin/skills/<name>/SKILL.md`, where the **directory**
carries the command name — `skills/init/SKILL.md` is the file that answers `/rhiza:init`.
Do **not** add a `name:` field to a `SKILL.md`: in a *plugin* skill it overrides that last
path segment, so a stale one silently renames the command.

Two habits go with that. Nothing enumerates the command surface by globbing a directory —
`_rhiza_layout.command_files()` returns `(name, path)`, and the four checkers that span the
repo's two halves import it rather than hardcoding a layout. And nothing may leave one
command name claimed by two files: `check_command_contracts.py` rule 10 fails the build on
that, because which file answers `/rhiza:<name>` at runtime is undefined, so moving a
command is a `git mv` and never a `cp`. The
[plugin docs](https://code.claude.com/docs/en/plugins) are the authority here, not this page.

`plugin/` itself is the choice — it keeps eight top-level directories down to four and
makes "is this shipped?" answerable from the path.

`${CLAUDE_PLUGIN_ROOT}` resolves to `plugin/`, so command prose is unchanged; only
source-checkout fallbacks gained the prefix. `plugin/scripts/_rhiza_layout.py` is the
single definition of the layout, imported by the checkers that span both halves.

## Runtime hooks

The prose gates below check the commands *before* they ship. They cannot check that a
correct command is *executed* correctly, which is what `plugin/hooks/hooks.json` is for: a
`PreToolUse` hook on `Bash`, auto-discovered from the plugin root, running
`plugin/scripts/hook_bash_guard.py`.

It reaches exactly three decisions:

| Situation | Decision | Why |
| --- | --- | --- |
| `make` combined with a pipe, redirect, or chain | `deny` | Breaks the allow-listed `Bash(make *)` match, so the user gets a permission prompt on every gate. The model reads the reason and re-runs bare — no human involved. |
| `git push --force`, `git tag -f` | `deny` | Irreversible, and no rhiza command needs either. `--force-with-lease` is deliberately *not* blocked. |
| A push whose target resolves to the default branch | `ask` | Escalated, not denied: a session with this plugin installed may be doing unrelated work in an unrelated repo. |

**It fails open by design.** Unparseable input, a missing `git`, an unreadable repo —
every one returns no decision, so the normal permission flow applies. A guard that
blocks when it is confused cannot be argued with, and would brick a session.

**Data spans are blanked before anything is analysed** — quoted strings *and* heredoc
bodies. A commit message is prose that routinely discusses `make` targets and force
pushes, and without that step `git commit -F - <<EOF … make deps replaces make deptry …
EOF` is denied as a chained `make`, with no way for the user to override it. Blanking
heredocs is also what makes `re.MULTILINE` safe on the `make` command-word pattern: only
once a body cannot match can `^` be widened to see the second line of a multi-line
command, which is a real invocation and previously slipped through.

The hook hardens the prose; it does not replace it. Every command stays correct with
hooks unavailable, so the rules are still stated where they apply.

## Make targets

```bash
make help        # list targets
make lint        # run prek against every file
make test        # run the script test suite (100% coverage gate)
make mutate      # mutation-test the sync core (slow; scheduled, not a PR gate)
make book        # build the documentation site into _book/
make book-serve  # serve the docs locally with live reload
make clean       # remove generated caches and artifacts
```

`make lint` runs every quality hook — mypy, interrogate (docstrings),
`doc-examples` (the doctests inside them), the test-layout check, the manifest
JSON/version-parity checks, and the three that gate the prose
(`command-contracts`, `prompt-wiring`, `docs-nav`). To run a single one, use
`uvx prek run <hook-id> --all-files` (e.g. `mypy`, `interrogate`,
`doc-examples`, `test-layout`, `manifest-version-parity`, `docs-nav`).

`interrogate` and `doc-examples` are a pair, and the split is the point:
interrogate answers *is there a docstring?* and `doc-examples` answers *is what
it claims still true?*, by executing the examples inside them and the fenced
blocks in `README.md`. A repo can hold 100% docstring coverage while documenting
nothing anyone can run, which is what the second hook exists to notice.

The runner is [`prek`](https://prek.j178.dev/), a drop-in reimplementation of
`pre-commit` in Rust. The config file keeps the `.pre-commit-config.yaml` name and
schema — prek reads it unchanged, and nothing in it is prek-specific — so the switch
shows up only in `make lint`, the CI `lint` job, and `uvx prek update` in place of
`pre-commit autoupdate`. Note the boundary: rhiza-*managed* repos get `pre-commit` from
the template, so the plugin's own prose about other people's repos still says
`pre-commit`, and that is not a leftover.

The prose hooks are the unusual ones. `command-contracts` treats each command as
a contract — its frontmatter parses, its bash blocks are valid shell, the scripts
and flags it names exist, and exactly the destructive commands
(`detach`, `release`) declare `disable-model-invocation: true`. `prompt-wiring`
keeps the `prompts/` procedures referenced and un-invocable — and, since a procedure's
*reason* for being un-invocable is as load-bearing as its wiring, fails the build when
shipped prose names a discovery location the plugin doesn't have. `docs-nav` requires a
`docs/` page and an `mkdocs.yml` nav entry for every command and procedure, in
both directions, so neither an undocumented command nor an orphaned page can ship.
`docs-reference-blocks` is its content half: each page carries a **Reference** table
generated from the command's frontmatter by `plugin/scripts/render_command_docs.py`, so a
renamed argument or a widened `allowed-tools` list cannot survive in the docs. Page
*existence* was checked; page *facts* were not.

Only that block is generated — the pages are hand-written prose, and
`docs/skills/maffay.md` is longer than the `SKILL.md` it documents. The renderer
appends and never edits a hand-written line.

### Shared hooks from `rhiza-hooks`

[`jebel-quant/rhiza-hooks`](https://github.com/Jebel-Quant/rhiza-hooks) publishes
pre-commit hooks for rhiza projects. This repo is deliberately **not** rhiza-managed,
so most of them key off a `.rhiza/` directory that isn't here and would be inert.

Adoption is therefore selective, and each candidate was **negative-tested** — break the
thing it checks, confirm the hook fails — before being enabled. Only
`check-workflow-make-targets` earned its place: it fails on
`run: make totally-not-a-target` in a workflow, and nothing here checked that before.
`check-makefile-targets` and `check-bumpversion-config` both *passed* with their subject
deliberately broken, because they look for a `pyproject.toml` this repo doesn't have, so
they were rejected. An enabled-but-inert hook is worse than no hook: it reads as
coverage that doesn't exist.

`update-readme-help` overlaps `plugin/scripts/sync_readme_help.py` in job but not in consumer.
The script is a **plugin** script that `/rhiza:docs` runs inside *someone else's* repo,
which need not have adopted rhiza-hooks; the hook only helps repos that have. Kept
local.

## Building the book

The book is [MkDocs](https://www.mkdocs.org/) + Material. Build it with no local
install using `uvx`:

```bash
uvx --with mkdocs-material mkdocs build   # → _book/
uvx --with mkdocs-material mkdocs serve   # live preview
```

`mkdocs.yml` inherits `docs/mkdocs-base.yml` (theme, extensions, plugins) and
adds the site metadata and navigation.

## Tests

```bash
make test                    # the whole suite, with a 100% coverage gate on scripts/
uvx pytest tests/ -k e2e -q  # the end-to-end tests (needs network, uv, cargo, go)
```

**The end-to-end tests are not opt-in.** They scaffold repos with the real `/init`
script chain, sync them from the real template, and assert the outcomes — a Python
repo on `github-project`, one on `gitlab-project`, a Rust crate and a Go module. They
used to be opt-in behind `RHIZA_E2E=1`, which is how `/rhiza:quality` shipped unable to run at
all: a suite nobody runs still reads as coverage. The fixtures are parameterised by
language — `(init command, profile, tools)` per language, with the assertions reading
their expectations from `plugin/scripts/language_profile.py` and from the synced tree.

The template ref they sync from is **pinned** in `tests/conftest.py`
(`PINNED_TEMPLATE_REF`), so a PR run never goes red merely because upstream released.
The cost of pinning is drift, so `.github/workflows/template-drift.yml` runs the same
tests weekly against the template's *latest* release and files a finding when the two
disagree. A red **Template drift** means upstream moved; a red **CI** means this repo
did.

Two things need tools the plugin itself does not: the Rust and Go fixtures need `cargo`
and `go` (`cargo init --lib` and `go mod init` build them), and half of
`tests/scripts/test_platform_cli.py` needs `glab`. Each skips when its tool is absent, and CI
installs or verifies all three so that never happens there. Nothing else skips: the pin is a rhiza release that defines every
profile `/rhiza:init` writes, so a ref that stops defining one **fails** the suite rather
than quietly narrowing it.

## CI/CD

- **CI** (`.github/workflows/ci.yml`) runs the hooks through prek (including a
  strict `mypy` type-check and 100% `interrogate` docstring coverage of
  `scripts/`) in the `lint` job, and the test suite under the 100% coverage gate
  in `tests`. A third job, `ci-gate`, `needs` both and is the single required
  status check named in `.github/rulesets/main-protection.json` — so those two can
  be renamed or restructured without re-applying the ruleset by hand.
- **Book** (`.github/workflows/book.yml`) builds the site on every push and
  deploys it to GitHub Pages from the default branch.
- **CodeQL** (`.github/workflows/codeql.yml`) scans the Python scripts and the
  workflows for security issues.
- **Scorecard** (`.github/workflows/scorecard.yml`) runs the OpenSSF Scorecard
  supply-chain analysis and publishes the score (README badge).
- **Links** (`.github/workflows/links.yml`) checks every link in the README, the
  top-of-repo prose and the docs site with lychee, weekly. `mkdocs build --strict`
  already catches an internal target that is missing; this catches the external
  ones, which rot without a commit. It files a deduped issue on failure.
