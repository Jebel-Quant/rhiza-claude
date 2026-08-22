# CLAUDE.md

Guidance for Claude Code sessions in **rhiza-claude** — the Claude Code plugin
marketplace providing the `rhiza` plugin.

## Read this first: which side of the boundary you're on

This repo **is the plugin**. It is *not* a rhiza-managed repo — there is no `.rhiza/`
directory, no `template.yml`, no `template.lock`, and nothing here is synced from
anywhere. That has two consequences worth internalising before you touch anything:

- **`/rhiza:quality` runs here in its degraded mode.** Its step-0 check looks for
  `.rhiza/template.yml` **and** `.rhiza/template.lock`; both are absent, so it skips
  every template-delivered gate, runs the targets this repo's own `Makefile` documents, and
  scores the design work. It used to refuse outright. Read any score it produces as
  what it says it is — a design-led assessment on this repo's own gates, not a Rhiza
  verdict, and not comparable to a managed repo's number.
- **The "locally-owned vs Rhiza-owned" scoping rule doesn't apply.** Every file here is
  locally owned. When you read that rule in `plugin/prompts/scorecard.md`, you're reading a
  rule *this repo ships for other repos*, not one that governs it — which is also why
  degraded mode inverts it: with no template, the `Makefile` and workflows are this
  repo's own work and are squarely in scope.

## Commands

```bash
make help           # list every target
make lint           # all prek hooks over every file
make audit          # bandit over the scripts, zizmor over the workflows
make complexity     # radon CC/MI — the census this file quotes; reports, never fails
make test           # pytest over tests/, 100% coverage gate on scripts/
make e2e            # only the end-to-end tests, no coverage gate (template-drift's target)
make portable       # everything except e2e, no coverage gate (the cross-platform CI job's target)
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
(`mypy`, `interrogate`, `doc-examples`, `test-layout`, `command-contracts`,
`prompt-wiring`, `prose-counts`, `manifest-version-parity`, `workflow-pins`).

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
`"source": "./plugin"`.

**Only three of the five directories inside `plugin/` are the spec's; the other two are
ours.** This file used to claim they were all "mandated by the plugin spec", which is
wrong, and the distinction matters because it is what tells you which ones you may move:

- **`skills/` and `hooks/` are discovery locations.** Claude Code finds components by
  looking for those names at the *plugin* root, so they cannot be renamed or nested. It
  also recognises `agents/`, `.mcp.json`, `.lsp.json`, `monitors/`, `bin/` and
  `settings.json` — none of which this plugin ships.
- **`prompts/` and `scripts/` are this repo's own conventions.** The spec has never heard
  of either. `prompts/` exists precisely *because* it is not a discovery location: a
  procedure placed there cannot be invoked as a slash command, which is the guarantee
  `check_prompt_wiring.py` enforces. That reasoning stands on its own and never needed the
  spec to back it.

**Every command is a skill: `plugin/skills/<name>/SKILL.md`, and the *directory* is the
command name.** `skills/init/SKILL.md` is the file that answers `/rhiza:init`.

Three habits go with that, and each is easy to undo by accident:

- **Never discover commands by globbing a directory.** `_rhiza_layout.command_files(root)`
  returns `(name, path)` and is the only supported way to enumerate the command surface.
  Four checkers import it. It also still resolves `COMMANDS_DIR` — the flat spelling this
  plugin does not use — so a stray flat file is held to every contract instead of being
  silently ignored. That tolerance is load-bearing in one direction only: don't
  "simplify" it away without also dropping rule 10 and the synthetic fixtures in
  `tests/scripts/` that cover it.
- **Never leave a command in two places.** Rule 10 of `check_command_contracts.py` fails
  the build when one name is claimed by two files, because which one wins at runtime is
  undefined. Moving a command means `git mv`, not `cp`.
- **Assert on a command's content, never on its path.** `tests/scripts/` resolves a command
  by name (`_command_text` in `test_check_prompt_wiring.py`); a hardcoded path is what made
  those tests break on a move that changed nothing they were checking.

Do **not** add a `name:` field to a `SKILL.md`. In a *plugin* skill (unlike a personal one)
`name` overrides the last segment of the command, so a stale one silently renames it.

| Path | What it is |
| --- | --- |
| `plugin/skills/<name>/SKILL.md` | The ten slash commands users invoke, namespaced `/rhiza:<name>`. The **directory** is the command name. |
| `plugin/prompts/*.md` | Eight **internal procedures** commands reach with `Read`. |
| `plugin/hooks/hooks.json` | A `PreToolUse` hook on `Bash`, auto-discovered from the plugin root. |
| `plugin/scripts/*.py` | Bundled, stdlib-only Python the prose calls. |
| `plugin/.claude-plugin/plugin.json` | The plugin manifest. |
| `tests/scripts/*.py` | Pytest suite mirroring `plugin/scripts/` 1:1. Not shipped. |
| `docs/` | The MkDocs site: `skills/`, `internals/`, `index.md`, `development.md`. |
| `paper/` | A LaTeX introduction, rebuilt by CI and published with the site. |
| `.claude-plugin/marketplace.json` | The marketplace catalogue. |

**`${CLAUDE_PLUGIN_ROOT}` resolves to `plugin/`**, so every
`"${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py"` in the prose is unaffected by the layout — a
skill reaches plugin-level scripts through that variable, not through `${CLAUDE_SKILL_DIR}`.
Only the *source-checkout fallback* carries the prefix now — `plugin/scripts/<name>.py`.
`plugin/scripts/_rhiza_layout.py` holds the one definition of where things live; the four
checkers that span both halves import it rather than hardcoding `plugin/` or a layout.

**`scripts/` is one gated tree, not a location.** Eight gates are scoped to
`plugin/scripts/` — mypy, interrogate, doc-examples, subprocess-discipline, the 100%
coverage floor, both radon bars, and `check_command_contracts`' script/flag resolution — and
six of them fail *open*. Bundling a script inside a skill directory to make that skill
self-contained would therefore drop it out of the bar rather than move it — which is why
every script lives in `plugin/scripts/`, `maffay.py` included, however self-contained its
skill looks. Changing that means widening all eight scopes deliberately, in its own PR.

**The tree also holds the non-Python assets those scripts copy out**, one directory per
kind: `plugin/scripts/licenses/*.txt` behind `set_license.py`, and
`plugin/scripts/completions/rhiza-completion.{bash,zsh}` behind
`install_completions.py`. Every gate above keys off `\.py$`, so an asset directory adds
nothing to check and drops nothing out of the bar — the point is only that a script and
what it writes stay together, resolved as `Path(__file__).parent / "<kind>"`. The two
shell scripts are worth one caveat: being shell, they fall outside every gate that keys
off `.py`, and being *copied* rather than run they fail silently — the install succeeds
and completion simply never works. `test_install_completions.py` parses each of them with
`bash -n` / `zsh -n`, which is the only thing standing in for the eight gates the Python
beside them gets. Keep that test if you touch them.

**Skills vs `prompts/` is the load-bearing distinction.** Procedures live outside every
discovery location specifically so they cannot be invoked as slash commands — that's the
guarantee, not an organisational preference. `plugin/scripts/check_prompt_wiring.py` enforces
six rules about it: each procedure declares it isn't a slash command, carries no
command frontmatter, never collides with a command name, is actually referenced
somewhere, and is never invoked as a command — and, rule 6, **no shipped prose names a
discovery location the plugin doesn't have.** Don't "tidy" a procedure into `skills/`.

**Rule 6 gates the reasoning, not the wiring, and its scope is deliberate.** Rules 1–5 check
that a procedure declares itself un-invocable; none reads *why*. A file can therefore pass
all five while justifying itself against a directory this plugin does not have — and an
argument from an absent constraint reads, to the next human or model, as a constraint that
no longer binds. Rule 6 fails the build on that class of claim. It
covers `plugin/`'s own markdown only, and its gated tokens are the six discovery-location
names Claude Code scans for (`agents`, `bin`, `commands`, `hooks`, `monitors`, `skills`),
unprefixed or under `plugin/` or
`${CLAUDE_PLUGIN_ROOT}/`. Two exclusions carry their weight: **this file is not checked**,
because specifying the rule means naming the very tokens it gates (the list above is a
rule-6 violation by construction), and prose about *another* repo's layout gets
`<!-- rhiza-layout-exempt: <dir>/ <reason> -->`, scoped to that directory in that file. The
reason is mandatory — a bare pragma doesn't match, so the violation stands. One exemption
exists today, at `plugin/prompts/design-analysis.md`.

**Procedures cannot become per-skill files**, either: `pr-base` is read by three commands
and `install-uv` by two, so a shared procedure has no single skill folder to live in.
`prompts/` stays at the plugin root.

Shared behaviour lives in the procedures, which is why `/init` and `/update` behave
identically where they overlap. `plugin/skills/init/SKILL.md` alone does not explain
`/rhiza:init`.

**The design split:** deterministic work belongs in tested Python; judgement belongs in
markdown. Parsing a lock file, merging synced files, comparing versions, drawing a
random song — those are scripts. Reading a repo and scoring it is prose.

**An underscore prefix means "not an entry point".** A command invokes
`scripts/<name>.py`; everything a script leans on lives in a `_`-prefixed sibling that no
command ever names. Four families, plus the sync core:

| Prefix | Owns |
| --- | --- |
| `_rhiza_*` | the sync core, and anything shared across unrelated commands — `_rhiza_toml` (add a TOML key, reformat nothing) serves the skeleton, `set_license` **and** `set_python_version`; `_rhiza_yaml` is the read/write façade over `_rhiza_yaml_parse`; `_rhiza_forge` answers *which forge is this* for both `platform_cli` and `pr_status` |
| `_skeleton_*` | one module per language behind `init_skeleton.py`, which is only the dispatcher and the CLI — each language's gap differs in kind, not degree |
| `_validate_*` | `validate.py`'s three halves: the `Log` sink, the language structure checks, the `template.yml` field checks |
| `_doc_examples_*` | `check_doc_examples.py`'s two halves: the doctests under a source root, and the README's fenced blocks. They share only a verdict, so the dispatcher runs each independently — a repo with no source root still gets its README checked |

Two consequences worth knowing before you move code. **The size and complexity bars are
measured, not taste** — no module over 500 lines, no block above cyclomatic C(12), every
maintainability index at A. `make complexity` reports both; it prints what it finds and
exits 0, so it tells you where you stand rather than failing the build. Run it bare, as
with every other target: only inside make does `UV_CONSTRAINT` bind, and a hand-run `uvx
radon` measures with whatever release is current instead of the pinned one. And the 1:1
test-layout rule binds these modules too, so extracting one is never a one-file change: it
needs its own `test__<name>.py`.

**Those bars stop at `plugin/scripts/`, and `tests/` is deliberately exempt.** Note the
path the target passes: it is the scope, not an example. A `/rhiza:quality` run in
degraded mode measures the whole repo — the census reports `.` as the source root — so
it will report what that exemption covers, and the numbers are not small:

| Tree | Blocks | Average | C-or-worse |
| --- | --- | --- | --- |
| `plugin/scripts` | 467 | A (4.01) | **0** |
| `tests` | 1479 | A (2.84) | **6** |

**Both rows are `make complexity` output — regenerate them there rather than editing them
here.** The target prints exactly these four figures per tree, which it did not always do:
it measured only `plugin/scripts` and passed `-a`, which averages just the blocks
surviving `-n C`, so this table's numbers had no source to be checked against. They were
committed once at 382 and 1201 and had drifted by roughly 15% before anyone re-measured.
The qualitative claims never moved, which is why nobody noticed — so treat a changed count
as routine and a changed *grade* as the signal.

Six C-grade blocks (worst `C(13)`, in `test_e2e_release_bumps_every_declared_location`),
and the ten largest modules in the repo are all test files, each at or past the 500-line
ceiling. **That is known and accepted, not an oversight.** An end-to-end test that syncs
a real template into a real repo is branchy because the scenario is, and the alternative
— splitting a fixture to satisfy a complexity grade — buys a better number by making the
test harder to follow. The bar exists to keep *shipped* code readable by the next person
who has to change it under time pressure; a fixture is read once, by someone already
holding the scenario in their head.

What the exemption does **not** license is the mirror image: a test so convoluted that a
failure is hard to diagnose is a real defect, and it should be fixed on that ground
rather than because radon graded it. Judge tests by whether a red one tells you what
broke.

**Script path convention.** Commands invoke scripts as
`"${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py"` — keep the quotes. In a source checkout
that variable is empty, so prose should offer the repo-relative fallback.

## Conventions

**`scripts/` is held to a hard bar**, all of it gated in `.pre-commit-config.yaml`:

- **stdlib-only** — no third-party imports. The plugin must work with no install step.
- **`mypy` strict** and **100% `interrogate` docstring coverage**.
- **Docstring examples are executed** — the `doc-examples` hook runs every `>>>` under
  `plugin/scripts/` with `doctest`, so an example that stops matching its output fails
  the build. Coverage says a docstring exists; this says it is still true. Examples are
  not required per module, but a wrong one is a defect, not a stale comment. Prefer them
  on the pure helpers, where a reader gets the rule without needing a fixture.
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

**`check_prose_counts.py` gates the other half of a prose claim: its arithmetic.** A
sentence saying how many commands, procedures or workflows there are is checked against
the tree — but only where an author marked it, with `rhiza-count: <subject>` in whatever
comment syntax the file speaks. The marker carries no number of its own, so there is
nothing to drift; it says only "this count is a total". That is deliberate and the design
was arrived at the hard way: reading every number followed by "commands" flags
"`pr-base` is read by three commands", which is correct English, and a gate that fails on
correct prose gets switched off. The trade is that an unmarked count is unchecked.

It exists because `paper/` had no gate at all, and `paper/` is what the release stamps
"true of release vX.Y.Z" — it claimed nine user-facing commands against ten for the whole
of v0.10.0. `Makefile` had the same drift ("the nine workflows" against ten). Both are
now marked.

**When adding or changing a command:**

1. Edit `skills/<name>/SKILL.md`; keep the frontmatter accurate and add no `name:` field.
2. Script-backed? Logic in `scripts/<name>.py`, tests in `tests/scripts/test_<name>.py`.
3. Add `docs/skills/<name>.md` **and** an `mkdocs.yml` `nav` entry. Write the prose
   only — run `plugin/scripts/render_command_docs.py` for the **Reference** block, which is
   generated from the frontmatter and gated by `docs-reference-blocks`.
4. Update `README.md` if it's a headline command.

**Versioning.** The two manifests must agree; `manifest-version-parity` enforces it.
Both are declared in `.bumpversion.toml`, so `bump-my-version` writes them together —
`/rhiza:release` drives it. Never hand-edit a version.

**The workflows' pins are gated the same way**, by `check_workflow_pins.py`
(`workflow-pins`): every remote `uses:` is a full SHA carrying a `# <version>` comment,
all call sites of one action repository agree on both, and every `astral-sh/setup-uv`
step passes a `version:` input — with all of those agreeing too. Both halves of a SHA pin
drift silently, and Dependabot watches only the SHA: it bumped `setup-uv` to v10.0.0 and
left one call site commented `# v7.1.1`, and the same file passed no `version:` input at
all, floating uv in the job that decides whether a release tag gets created. The uv
version is duplicated at five call sites by necessity — the action reads an input, not a
file — so this hook is what makes it one value. Bump them together; `uv self version`
locally is how you pick it.

**Commits** follow Conventional Commits; `CHANGELOG.md` is generated from them. Branch
off `main` and open a PR — never push to the default branch.

## Gotchas

- **`docs/reports/`, `docs/paper/`, `_book/`, `_tests/` are build outputs**, all
  gitignored. `make book` copies test reports into the site and renders the coverage
  badge *from the measured run*, so a published number can't be asserted by hand.
- **`markdownlint` excludes `plugin/skills/`** — a `SKILL.md` is a prompt, not docs. The
  repo root (this file included) is linted.
- **`make book` depends on `paper` and `test`** by design: the docs link the PDF and
  `mkdocs build --strict` fails on a missing target, so neither can silently go stale.
- **The end-to-end tests are part of `make test`, not an opt-in extra.** `make e2e` and
  `make portable` exist, but both are *narrowings* with exactly one caller each — `e2e` for
  the weekly template-drift job, which needs them without the coverage gate, and `portable`
  (their complement) for the `cross-platform` CI job on macOS and Windows, where the e2e
  fixtures' toolchains aren't the question and a filtered run can't reach the coverage
  floor. Neither is a flag that turns anything on. Every `make test` runs them. They sync real
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
