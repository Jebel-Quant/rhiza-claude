# rhiza-claude

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Coverage](https://jebel-quant.github.io/rhiza-claude/coverage-badge.svg)](https://jebel-quant.github.io/rhiza-claude/reports/html-coverage/)
[![CodeFactor](https://www.codefactor.io/repository/github/Jebel-Quant/rhiza-claude/badge)](https://www.codefactor.io/repository/github/Jebel-Quant/rhiza-claude)

A [Claude Code](https://claude.com/claude-code) plugin marketplace providing the
**`rhiza`** plugin — slash commands for working in rhiza-managed repos (template
sync, code-quality scoring, and README/doc upkeep).

📖 **Documentation:** <https://jebel-quant.github.io/rhiza-claude/> — a dedicated
page for every command. Build it locally with `make book`.

## What this is for

Ten repos need the same CI, `Makefile`, gates and docs build — and copied scaffolding
drifts. [**rhiza**](https://github.com/jebel-quant/rhiza) is that scaffolding kept once,
in a **template repository**. **rhiza-claude** is how a repo adopts it: sync from a
pinned template release, then get scored on the result.

**Two repos, one boundary.** The template owns CI, the `Makefile`, `.rhiza/rhiza.mk` and
the docs base; your repo owns source, tests, `pyproject.toml` and README prose. A sync
writes **only template-owned paths** — the ones the last sync recorded — so your code
can't be swept in. There is no blanket `git add --all` in the flow.

**"rhiza-managed" is two files**, answering different questions: `.rhiza/template.yml`
is a *pointer* (which template, which pinned ref — what we'd sync *from*), and
`.rhiza/template.lock` is a *record* (repo, ref, SHA, timestamp, strategy, every managed
file — what actually arrived). They can disagree, which is why `/rhiza:status` reports
both and `/rhiza:quality` checks for `.rhiza/template.yml` **and** `.rhiza/rhiza.mk`
before scoring: its gates *are* the synced `make` targets, so without them it drops to
a **degraded mode** — template gates skipped, your own `make` targets run, design
scored in full, and the report says so. `/rhiza:release` needs neither.

**The order still matters** — `/rhiza:init` → merge → `/rhiza:update` → merge →
`/rhiza:quality`. `/init` writes one file of its own and **syncs nothing**; `/update`
performs the first sync; `/quality` needs that content for its *full* assessment. So
"`/init` ran and no CI appeared" is the expected result of step one, and a `/quality`
run before the sync gives you the narrower score rather than nothing.

**Two kinds of markdown, and the difference is enforced.** `skills/` holds
the ten slash commands you invoke; `prompts/` holds eight **internal procedures** they
`Read` — kept outside both so they can't be invoked directly. The procedures are where
shared behaviour lives, which is why `/init` and `/update` behave identically where they
overlap.

**Why prose commands at all:** deterministic work belongs in tested code, judgement
belongs in markdown. The bundled stdlib-only Python does what has one right answer
(parsing the lock, merging synced files, comparing versions); the markdown does what
needs a reading of your repo. CI gates the prose too, so a command naming a script or
flag that no longer exists fails the build instead of failing mid-task in front of you.

👉 **New here?** The [documentation site](https://jebel-quant.github.io/rhiza-claude/)
has the full introduction and a worked first run — empty directory to synced, scored
repo.

## Install

```text
/plugin marketplace add Jebel-Quant/rhiza-claude
/plugin install rhiza@rhiza-claude
```

Or, from a shell, `make install` runs the equivalent `claude` CLI commands:

```bash
make install
```

The commands then appear namespaced under the plugin: `/rhiza:init`,
`/rhiza:update`, `/rhiza:quality`, `/rhiza:docs`. Type `/rhiza`
to have Claude Code autocomplete them.

### Install a specific version

By default the marketplace tracks this repo's default branch, so `/plugin
install` pulls the latest release. To pin to a specific published version,
append that version's git tag as a `#<ref>` suffix when you add the marketplace
(see the [releases page](https://github.com/Jebel-Quant/rhiza-claude/releases)
for available tags):

```text
/plugin marketplace add Jebel-Quant/rhiza-claude#v0.11.0
/plugin install rhiza@rhiza-claude
```

The same `#<ref>` suffix works from a shell:

```bash
claude plugin marketplace add Jebel-Quant/rhiza-claude#v0.11.0
claude plugin install rhiza@rhiza-claude
```

Pinning happens at the marketplace layer, not per plugin — once the marketplace
is added, `/plugin install` uses whatever ref it points at. To switch versions,
remove the marketplace and re-add it at the tag you want, which works in either
direction — an older release as readily as a newer one:

```text
/plugin marketplace remove rhiza-claude
/plugin marketplace add Jebel-Quant/rhiza-claude#<tag>
```

`<tag>` is any published tag from the [releases
page](https://github.com/Jebel-Quant/rhiza-claude/releases). It is a placeholder
here on purpose: the two examples above pin the current release and are rewritten
by `bump-my-version` on every release, but this one has to name a *different* tag
to show that switching goes both ways — so a literal version here would be one no
release could keep current, and it silently aged three minor versions before
anyone noticed.

## Prerequisites

The commands drive a rhiza-managed repo with [`uv`](https://docs.astral.sh/uv/) —
install it once:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

You don't have to do this ahead of time, though: both `/rhiza:init` and
`/rhiza:update` check for `uv` as their first step and offer to install it (with your
approval) on any platform. `git` and `make` are also used but are near-universal, and
the plugin's own bundled scripts are stdlib-only Python — no `rhiza` CLI required.

## Commands

- **`/rhiza:init`** — make the current folder rhiza-managed. It writes **one file**
  itself — `.rhiza/template.yml`, the pointer at a template repo and pinned ref — and
  delegates the rest to the internal procedures (see [Internals](#internals)):
  install-uv, then skeleton, then license. It detects platform/owner/name from an
  existing `origin` (or asks), picks the language (Python, Go or Rust — **the three are
  not equally supported; see [Language support](#language-support)**) and template
  repo (`jebel-quant/rhiza` for all three — the template is multi-language, layering
  a `python-core`/`rust-core`/`go-core` bundle on a neutral `core` — or a fork) plus
  its latest release as the initial pin —
  checking that ref actually defines the profile it's about to name, since an
  unsatisfiable pointer merges cleanly and then fails the *first* `/rhiza:update` — and
  opens a PR on a `rhiza_init_<date>` branch — never pushing to the
  default branch (a brand-new repo's base branch is created by you). It runs **no
  sync and no gates**: the template content (CI, `Makefile`, `rhiza.mk`, docs base)
  arrives when you run `/rhiza:update` after the PR merges — a second PR.
- **`/rhiza:update`** — sync the repo to the latest (or a given) template release:
  bump the `ref` in `.rhiza/template.yml`, run the bundled sync, resolve conflicts by
  taking the upstream side, and open a PR containing **only template-owned files** —
  the paths `.rhiza/template.lock` records, never a blanket `git add --all`, so your
  own source is never swept in. The template repo is read from `template.yml`, so a
  fork works too. Runs no gates and files no issues: use
  `/rhiza:quality` for a scorecard.
- **`/rhiza:quality`** — run the rhiza code-quality gate (lint, types, docs,
  deps, security, tests, complexity, architecture) and score the repo. It also checks
  the documentation for **truth rather than presence**: the `>>>` examples in your
  docstrings, and every fenced block in `README.md` — shell parsed with `bash -n`,
  Python with `compile()`, and a `python` fence diffed against the ```result``` block
  that follows it. `interrogate` can only tell you a docstring exists; this is what
  tells you it is still right. Shell fences are never executed, and executing anything
  at all is opt-in — a module it cannot import is reported *unmeasured*, never failed.
- **`/rhiza:docs`** — create or refresh the repo's three top-of-repo documentation
  files: `README.md` (with the standard badge set), `CLAUDE.md`, and `mkdocs.yml`.
  Detects platform, owner/repo and project metadata at runtime, preserves hand-written
  prose, and keeps the README's `make help` target list in lockstep with the real
  `Makefile`. Badges are generated with **omit, don't fake** — a badge whose backing
  fact isn't detected is never emitted. Writes files only; no commit, no PR.
- **`/rhiza:release`** — release **through a pull request**: **table up the legal next
  versions** and let you pick (it never suggests or defaults to one), **guard that the
  choice strictly increases** past every prior release, then let `bump-my-version` write it
  into every location the repo declares in `[tool.bumpversion]` — `pyproject.toml`, plugin
  manifests, self-referencing CI stub pins — regenerate `CHANGELOG.md`, and open a release
  PR. Because the locations are declared rather than inferred, a dependency that happens
  to share the version number is never rewritten. **Run it again after the PR merges** and
  it tags the merged commit and pushes the tag: a tag must name a commit on the default
  branch, and a squash-merge rewrites the SHA, so the commit worth tagging doesn't exist
  until you merge. It works out which of the two phases it's in from the repo's own state.
  The merge is the decision; everything after it is mechanical, and what keeps it safe is
  the guard refusing a non-increasing or already-existing tag. **In this repo a
  push-to-`main` workflow does that second phase for you**, so a release is: run it, merge.
- **`/rhiza:remote`** — ask the forge what CI actually said about the repo's open
  requests, then diagnose and fix the red ones. `/rhiza:quality` files findings as
  issues, those issues become branches, and those branches become requests that were
  green when they left — **local green and origin green are different claims, and only
  the second one merges**. It normalises GitHub's and GitLab's very different answers
  into one vocabulary, prints the exact drill-down command under each failing check, and
  sorts every failure into one of four kinds — real defect, environment difference,
  infrastructure flake, known upstream — because only one of them is a code fix. Fixes
  land on the request's own branch; never the default branch, never a force-push. **It
  will not make a check green by weakening it**: if the honest fix is out of reach it
  leaves the build red and says why.

### The documentation checks itself

The fence below is not an illustration. `/rhiza:quality`'s example gate executes it and
diffs its output against the expected-output block underneath, so if the shipped
`classify_host` ever stops refusing a host that merely *embeds* a known forge domain,
this README turns the build red rather than quietly going on claiming otherwise.

```python
import sys

sys.path.insert(0, "plugin/scripts")
from _rhiza_forge import classify_host

for host in ("github.com", "code.gitlab.com", "gitlab.acme.io", "github.com.evil.example"):
    print(f"{host} -> {classify_host(host)}")
```

```result
github.com -> github
code.gitlab.com -> gitlab
gitlab.acme.io -> gitlab
github.com.evil.example -> None
```

That last line is the one that matters: `github.com.evil.example` is not a subdomain of
`github.com`, and a forge detector that guessed would act against the wrong host.

### Internals

Not slash commands. These are **internal procedures** under `prompts/` —
deliberately outside `skills/` so they can't be invoked directly. `/rhiza:init` and
`/rhiza:update` read and follow them, and most are backed by a deterministic,
stdlib-only script.

- **install-uv** (`plugin/prompts/install-uv.md`) — make sure `uv`, the plugin's one hard
  dependency, is installed, via the official astral.sh installer, Homebrew, or
  winget. Never installs without approval; sorts out the `PATH` step the installer
  leaves behind. The **first step of both `/rhiza:init` and `/rhiza:update`**.
- **pr-base** (`plugin/prompts/pr-base.md`) — a work branch based on an up-to-date remote
  default branch, which is **never pushed to**: when it doesn't exist yet, *you* create
  the repo with an empty README rather than the command pushing one. Shared by
  `/rhiza:init` and `/rhiza:update`, so both behave identically.
- **skeleton** (`plugin/prompts/skeleton.md` → `plugin/scripts/init_skeleton.py`) — `uv init --lib`
  when there's no `pyproject.toml`, then the shape the template's gates require: a
  package docstring in place of uv's `hello()` placeholder, the description, and the
  `[project.urls]` and `[dependency-groups]` entries the synced pyproject gate
  asserts. Idempotent and additive. The template never ships a `pyproject.toml`, so
  the quality gates need this to have run.
- **license** (`plugin/prompts/license.md` → `plugin/scripts/set_license.py`) — the SPDX
  `license`/`license-files` metadata in `pyproject.toml` plus the `LICENSE` file's
  full text (MIT, Apache-2.0, BSD-3-Clause bundled). Overwriting an existing
  `LICENSE` needs `--force`; `none` clears the metadata. Never writes a deprecated
  `License ::` trove classifier.
- **design-analysis** (`plugin/prompts/design-analysis.md`) — the complexity and architecture
  evidence no `make` gate measures: radon CC/MI, module sizes, the import graph, layering
  direction, and cycles including ones hidden behind function-local imports. Gathers
  evidence; doesn't judge.
- **scorecard** (`plugin/prompts/scorecard.md`) — the 1–10 rubric: the subcategory list, the
  coverage bar, the findings format, the issue menu, and the **scoping rule** that stops
  a managed repo being marked down for its own template.
- **python-version** (`plugin/prompts/python-version.md` → `plugin/scripts/set_python_version.py`)
  — pin `requires-python` and rewrite the `Programming Language :: Python :: X.Y`
  classifiers to the supported range (3.11–3.14; never a bare `:: 3`), and sync
  `.python-version`.

### Repo utilities

Thin, **read-only**, stdlib-only commands backed by bundled scripts — they work
without the `rhiza` CLI installed, reading `.rhiza/template.lock` /
`.rhiza/template.yml` directly where they need a repo at all. None of them writes
anything.

- **`/rhiza:status`** — report both halves of the repo's rhiza state: whether
  `.rhiza/template.yml` is valid (what you'd sync *from*), and what
  `.rhiza/template.lock` records as actually synced (repository, ref, SHA, timestamp,
  strategy). They can disagree in both directions, so reporting one alone misleads.
  Add `--files` (alias `--tree`) to list the managed files as a directory tree, or
  `--check` to compare the pinned ref against the latest upstream release.
  Read-only.
- **`/rhiza:maffay`** — return a bonmot from a random Peter Maffay song, for the middle
  of a long refactor. Takes an optional theme keyword (`mut`, `sommer`, `nessaja`, …) or
  part of a song title. The draw lives in `plugin/scripts/maffay.py` because a model asked for
  a random song reaches for the same two hits every time. Quotes the **title line**
  only, attributed — no lyric bodies — and the `Für uns:` gloss beside it is ours, not
  Maffay's. Needs no repo, no git and no network.

### Machine setup

- **`/rhiza:completions`** — install make tab-completion for bash, zsh or both, so
  `make <TAB>` lists a project's targets. **The one command that writes outside a repo**:
  the destinations are under `${XDG_DATA_HOME:-$HOME/.local/share}`, which is also why it
  isn't model-invocable — you have to name it. The completion is generic (it parses the
  make database in the current directory), so **install it once per machine**, not once per
  repo; this is the plugin taking over a job the template used to do by syncing four
  identical files into every managed repo. The installed names are the shells' generic
  `make` / `_make`, so a completion this plugin didn't write is reported and left alone
  rather than overwritten — `--force` is opt-in.

### Destructive

- **`/rhiza:detach`** — detach the repo from rhiza: delete every rhiza-managed file
  listed in `.rhiza/template.lock`, prune the emptied directories, and remove the lock.
  This is the only command that removes files wholesale; it prompts for confirmation
  unless `--force` is passed. It detaches a **repo**, not the plugin — the inverse of the
  sync, not of the installation, so uninstalling the plugin via `/plugin` is a different
  thing entirely and leaves every synced file in place.

## Language support

`/rhiza:init` offers Python, Go and Rust, and all three point at the same multi-language
template. They are **not equally supported**, and it is worth knowing which you're
signing up for before the four-step bootstrap rather than after.

| | Python | Rust | Go |
| --- | --- | --- | --- |
| `/init`, `/update`, `/status`, `/release`, `/detach` | ✅ | ✅ | ✅ |
| Local toolchain from the template | ✅ | ✅ cargo, clippy, nextest, llvm-cov, cargo-deny | ✅ go test, golangci-lint, govulncheck, revive |
| Hosted CI workflows | ✅ | ❌ none yet | ❌ none yet |
| `/quality` gate list | ✅ known and named | ⚠️ discovered at runtime | ⚠️ discovered at runtime |
| Test-layout parity subcategory | ✅ | n/a | n/a |
| Executable-documentation gate | ✅ docstrings + README | ⚠️ README fences only | ⚠️ README fences only |

**Python is the fully-supported axis.** `/rhiza:quality`'s gate list *is* the Python
profile — the one the plugin has actually run against. On a Rust or Go repo it probes
the Makefile with `check_make_targets.py`, scores the targets it discovers, and marks
the language-specific subcategories out-of-scope. That is deliberate: a hand-written
table of targets for templates this plugin has never run against would be prose
asserting things it can't back. But it does mean a Rust or Go scorecard rests on a
narrower base than a Python one, and `/quality` now says so in its own output.

There is deliberately no `rust-github-project` or `go-github-project` profile — those
are almost entirely CI workflows, and rhiza's `github`/`gitlab` bundles still ship
Python ones. Add hosted CI yourself until those land.

## Layout

**The shipped plugin lives in `plugin/`; everything that builds or checks it stays at
the repository root.** `.claude-plugin/marketplace.json` points at it with
`"source": "./plugin"`, which is the documented way to keep a plugin in a subdirectory
of its marketplace repo.

Two of the directories inside are the spec's and two are this repo's.
`skills/` and `hooks/` are **discovery locations** — Claude Code finds
components by those names at the plugin root, so they cannot be renamed. `prompts/` and
`scripts/` are local conventions the spec has never heard of; `prompts/` exists precisely
*because* it is not a discovery location, so a procedure kept there cannot be invoked as a
slash command.

All ten commands are skills: `plugin/skills/<name>/SKILL.md`, where the **directory**
names the command, so `skills/init/SKILL.md` is what answers `/rhiza:init`. Check the
[plugin docs](https://code.claude.com/docs/en/plugins) rather than this table before
assuming what the spec requires.

| Path | Purpose |
| --- | --- |
| `.claude-plugin/marketplace.json` | Marketplace manifest listing the `rhiza` plugin. Stays at the repo root — that's where `/plugin marketplace add` looks. |
| `plugin/` | **The plugin as shipped.** Everything below is inside it. |
| `plugin/.claude-plugin/plugin.json` | The `rhiza` plugin manifest. |
| `plugin/skills/` | The plugin's ten slash commands (`<name>/SKILL.md`, the directory naming the command). |
| `plugin/prompts/` | Internal procedures the commands `Read` — deliberately not commands, so users can't invoke them. |
| `plugin/hooks/` | `hooks.json` — a `PreToolUse` hook guarding Bash calls at runtime (compound `make`, force-push, push to the default branch). Fails open. |
| `plugin/scripts/` | Bundled stdlib-only Python the commands and procedures drive, plus the non-Python assets they copy out (`licenses/`, `completions/`). |
| `tests/scripts/` | Pytest suite mirroring `plugin/scripts/` 1:1. Not shipped. |
| `docs/` | The MkDocs site. Not shipped. |
| `paper/` | A LaTeX introduction — the long form of the framing above, with figures captured from real command output (`render_figures.py`). `make paper` builds it; CI rebuilds it on every commit and [publishes the PDF with the docs site](https://jebel-quant.github.io/rhiza-claude/paper/rhiza-claude-intro.pdf). |

Inside a command, `${CLAUDE_PLUGIN_ROOT}` resolves to `plugin/`, so
`"${CLAUDE_PLUGIN_ROOT}/scripts/sync.py"` is unchanged by the move. Only the
**source-checkout fallback** paths gained the prefix: `plugin/scripts/sync.py`.

## Contributing

Branch off `main`, make the change, and open a PR — CI runs the same
`make lint && make test` you can run locally, so a green pair means a green PR.
[CONTRIBUTING.md](./CONTRIBUTING.md) has the details: the prerequisites, the
checklist for adding or changing a command, and the commit conventions the
changelog is generated from.

Once a change lands on `main`, installed users pick it up the next time the
marketplace refreshes.
