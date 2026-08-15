# rhiza-claude

A [Claude Code](https://claude.com/claude-code) plugin marketplace providing the
**`rhiza`** plugin — slash commands for working in
[rhiza](https://github.com/jebel-quant/rhiza)-managed repos: template sync,
code-quality scoring, and README/doc upkeep.

## The problem it solves

Every repo you own needs roughly the same scaffolding: CI workflows, a `Makefile`, lint
and type and coverage gates, a docs build. Copy that into ten repos and you have ten
copies drifting apart — a workflow fixed in one, a gate loosened in another, and no way
to tell which repo has which vintage.

**rhiza** is the shared original: one multi-language *template repository*
([`jebel-quant/rhiza`](https://github.com/jebel-quant/rhiza), for Python, Rust and
Go alike) holding that scaffolding once. **rhiza-claude** — this plugin — is
how a repo adopts it, keeps up with it, and gets told how it's doing: it syncs your
repo from a pinned template release and scores the result.

!!! note "Python is the fully-supported axis"
    All three languages sync, update, release and report the same way. What differs is
    the far end: **Rust and Go have no hosted CI workflows yet**, and
    [`/rhiza:quality`](skills/quality.md)'s gate list is the Python profile, so on a
    Rust or Go repo it scores the targets it *discovers* in your Makefile and marks
    language-specific subcategories out-of-scope. A worked first run below is Python;
    see [Language support](#language-support) for the full comparison.

## The two-repo model

Two repositories, and the boundary between them is the whole idea:

| | owns | who changes it |
| --- | --- | --- |
| **the template** | CI stubs, `Makefile`, `.rhiza/rhiza.mk`, the docs base | upstream — you receive it |
| **your repo** | source, tests, `pyproject.toml`, README prose | you — the sync never touches it |

A sync is therefore not a copy of the template over your repo. `/rhiza:update` writes
**only template-owned paths**, and it knows which those are because the last sync
recorded them. Your `src/` is never in that set, so it can never be swept in — there is
no blanket `git add --all` anywhere in the flow.

## What "rhiza-managed" means

Two files under `.rhiza/`, and they answer different questions:

| file | it is | question it answers |
| --- | --- | --- |
| `.rhiza/template.yml` | a **pointer** — template repo + pinned `ref` | what *would* we sync from? |
| `.rhiza/template.lock` | a **record** — repo, ref, commit SHA, timestamp, strategy, every managed file | what *was* delivered, and when? |

**Intent versus outcome.** They can disagree in both directions: a freshly `/init`-ed
repo has a valid pointer and no lock at all, and a long-synced repo can have a lock
beside a pointer someone has since broken by hand. That's why
[`/rhiza:status`](skills/status.md) reports both halves, and why
[`/rhiza:quality`](skills/quality.md) checks for `.rhiza/template.yml` **and**
`.rhiza/rhiza.mk` before it runs: every gate it scores is a `make` target the sync
delivers, so scoring an unsynced repo would report it as broken rather than as
unsynced. (By contrast [`/rhiza:release`](skills/release.md) requires neither — it
reads the repo's own `[tool.bumpversion]` config, so it works on any git repo.)

## The intended path

```mermaid
flowchart LR
    A["empty or existing repo"] -->|"/rhiza:init"| B["PR: .rhiza/template.yml<br/>+ skeleton + LICENSE"]
    B -->|"you merge"| C["rhiza-managed<br/>(no lock yet)"]
    C -->|"/rhiza:update"| D["PR: template-owned files<br/>+ .rhiza/template.lock"]
    D -->|"you merge"| E["managed and synced"]
    E -->|"/rhiza:quality"| F["scorecard + findings"]
```

Three commands, **two PRs you merge yourself**, in that order:

1. **`/rhiza:init`** writes exactly one file of its own — `.rhiza/template.yml` — and
   **deliberately syncs nothing.** No CI, no `Makefile`, no gates arrive here.
2. **`/rhiza:update`** performs the first sync, which is what brings the template
   content in and writes `.rhiza/template.lock`.
3. **`/rhiza:quality`** needs that lock's worth of content to exist, so it comes third.

Running them out of order isn't dangerous, it just stops early and says so — but the
sequence is worth knowing before you start, because "`/init` and nothing happened" is
the expected outcome of step 1, not a failure.

## Commands and procedures

The plugin ships two kinds of markdown, and the difference is enforced rather than
conventional:

- **`skills/<name>/SKILL.md` → slash commands** you invoke: nine of them, each with a
  page here. The *directory* carries the command name, so `skills/init/SKILL.md` is the
  file that answers `/rhiza:init`.
- **`prompts/*.md` → internal procedures**: eight shared steps a command reaches with
  the `Read` tool, deliberately kept *outside* `skills/` so they cannot be invoked
  directly.

That second point is the load-bearing one. Claude Code finds components by scanning
particular directory names at the plugin root — `skills/` and `hooks/` are two of them,
and this plugin ships both. `prompts/` is deliberately *not* one, which is the guarantee:
a procedure kept there **cannot** be reached as a slash command.

Procedures are not implementation trivia — they're where the shared behaviour lives, so
`skills/init/SKILL.md` alone doesn't explain what `/rhiza:init` does. Installing `uv`,
choosing a work branch, scaffolding a `pyproject.toml`, pinning a Python version, writing
a licence, gathering design evidence, applying the scoring rubric, recording which
upstream failures are known: all of that is a procedure, which is exactly why
`/init` and `/update` behave identically where they overlap. Nor can they be folded into
the skills that read them — `pr-base` is read by three commands and `install-uv` by two,
so a shared procedure has no single skill folder to live in. They're documented under
[Internals](#internals) below.

## Why the commands are prose

Because the split is deliberate: **deterministic work belongs in tested code,
judgement belongs in markdown.**

The bundled Python under `scripts/` does the parts with one right answer — parsing the
lock, merging synced files, comparing versions, computing candidate bumps — and is
stdlib-only, type-checked and covered by tests. The markdown does the parts that need a
reading of your repo: which findings matter, whether a breaking change should spend the
1.0 signal, what to preserve in a README someone wrote by hand.

That's also why the prose itself is gated in CI: a command that names a script, a flag
or another command that no longer exists fails the build rather than failing in front of
a user mid-task.

## What it needs

Honest scope: **[`uv`](https://docs.astral.sh/uv/) is the one hard dependency**, and
both `/init` and `/update` offer to install it as their first step. `git` and `make`
are used and are near-universal. The plugin's own scripts are **stdlib-only Python** —
there is no `rhiza` CLI to install, which is the most common point of confusion about
what this needs.

## Language support

`/rhiza:init` offers Python, Go and Rust, and all three point at the same
multi-language template — the language selects a *profile* (`github-project`,
`rust-local`, `go-local`), never a different repository. They are **not equally
supported**, and the difference is worth knowing before the bootstrap, not after.

| | Python | Rust | Go |
| --- | --- | --- | --- |
| `/init`, `/update`, `/status`, `/release`, `/detach` | ✅ | ✅ | ✅ |
| Local toolchain from the template | ✅ | ✅ cargo, clippy, nextest, llvm-cov, cargo-deny | ✅ go test, golangci-lint, govulncheck, revive |
| Hosted CI workflows | ✅ | ❌ none yet | ❌ none yet |
| `/quality` gate list | ✅ known and named | ⚠️ discovered at runtime | ⚠️ discovered at runtime |
| Test-layout parity subcategory | ✅ | n/a | n/a |

**Python is the fully-supported axis.** [`/rhiza:quality`](skills/quality.md)'s gate
list *is* the Python profile — the one this plugin has actually run against. On a Rust
or Go repo it probes the Makefile with `check_make_targets.py`, scores the targets it
discovers, and marks language-specific subcategories out-of-scope.

That is a deliberate trade. A hand-written table of targets for templates the plugin has
never run against would be prose asserting things it cannot back; discovery degrades
honestly where a guessed table would lie. The cost is that a Rust or Go scorecard rests
on a narrower base than a Python one — so `/quality` states in its own output which
gates it discovered and which subcategories it skipped.

There is deliberately no `rust-github-project` or `go-github-project` profile: those are
almost entirely CI workflows, and rhiza's `github`/`gitlab` bundles still ship Python
ones. Until those land, add hosted CI yourself.

The worked first run below is Python.

## Install

```
/plugin marketplace add Jebel-Quant/rhiza-claude
/plugin install rhiza@rhiza-claude
```

Or, from a shell:

```bash
make install
```

The commands appear namespaced under the plugin — type `/rhiza` to have Claude
Code autocomplete them.

## First run, start to finish

An empty directory to a managed, synced, scored repo. Two PRs, both merged by you.

### 0. A git repo with a remote

```bash
mkdir my-lib && cd my-lib && git init
gh repo create my-lib --private --source=. --push   # or create it in the UI
```

`/init` never pushes to your default branch, so if the repo doesn't exist upstream yet
it asks *you* to create it (an empty README is enough) rather than pushing one itself.
Then start Claude Code in that directory.

### 1. `/rhiza:init` — become rhiza-managed

```
/rhiza:init
```

It detects platform, owner and name from `origin` (asking when it can't), picks the
language and template repo, resolves the template's **latest release** as the initial
pin, and opens a PR on a `rhiza_init_<date>` branch containing:

| written by | file |
| --- | --- |
| the command itself | `.rhiza/template.yml` — the pointer and pinned `ref` |
| the skeleton procedure | `pyproject.toml` (via `uv init --lib`), `src/`, `.python-version` |
| the license procedure | `LICENSE` + the SPDX metadata in `pyproject.toml` |

**No CI, no `Makefile`, no `rhiza.mk`, no `.rhiza/template.lock`.** `/init` runs no sync
and no gates by design — the template content is a *separate* PR, so the two are
reviewable apart. If you expected workflows to appear here, nothing has gone wrong.

Merge that PR.

### 2. `/rhiza:update` — the first sync

```
/rhiza:update
```

This is the step that brings the template in. It bumps the `ref` in `template.yml` to
the newest template release, syncs, resolves any conflict by **taking the upstream
side**, and opens a second PR containing the template-owned files —
`.github/workflows/`, `Makefile`, `.rhiza/rhiza.mk`, the docs base — plus
`.rhiza/template.lock` recording exactly what was delivered.

Only paths the lock names are staged, so nothing of yours is included even if it changed
in your working tree. Merge that PR too.

### 3. `/rhiza:status` — confirm both halves

```
/rhiza:status --files
```

Read-only. It validates the pointer *and* prints what the lock records: template repo,
ref, commit SHA, timestamp, strategy, and — with `--files` — the managed files as a
tree. This is how you tell "managed and synced" from "managed but never synced".

### 4. `/rhiza:quality` — get scored

```
/rhiza:quality
```

Now the gates exist as real `make` targets, so this works: lint, types, docs, deps,
security, tests, test layout, complexity, architecture → a 1–10 scorecard with findings,
and an optional menu to file them as issues. It proposes fixes but applies none.

### Afterwards

- `/rhiza:update` again whenever the template cuts a release (`/rhiza:status --check`
  compares your pin against the latest).
- `/rhiza:docs` to create or refresh `README.md`, `CLAUDE.md` and `mkdocs.yml` — it
  preserves hand-written prose.
- `/rhiza:remote` once a fix is open as a request — it reads what CI on the origin said
  and fixes the red ones. Needs no `.rhiza/` either.
- `/rhiza:release` when you want to cut a version. It needs no `.rhiza/` at all.

## Commands

These are the AI-driven workflow commands. Each has its own page.

| Command | What it does |
| --- | --- |
| [`/rhiza:init`](skills/init.md) | Make the repo rhiza-managed: write `.rhiza/template.yml`, delegate the skeleton + license, open a PR. |
| [`/rhiza:update`](skills/update.md) | Sync to the latest template release and open a PR with **only** template-owned files. |
| [`/rhiza:quality`](skills/quality.md) | Run the code-quality gate and score the repo 1–10 across eight categories. |
| [`/rhiza:docs`](skills/docs.md) | Create or refresh `README.md`, `CLAUDE.md`, and `mkdocs.yml`. |
| [`/rhiza:release`](skills/release.md) | Release by PR: pick the next version from a table, bump, changelog, open the PR — then tag the merged commit on a second run. |
| [`/rhiza:remote`](skills/remote.md) | Read what CI on the origin said about the open requests, then diagnose and fix the red ones on their own branches. |

## Repo utilities

Thin, **read-only**, stdlib-only commands backed by bundled scripts — they read
`.rhiza/template.lock` / `.rhiza/template.yml` directly and work without the
`rhiza` CLI installed. Neither writes anything.

| Command | What it does |
| --- | --- |
| [`/rhiza:status`](skills/status.md) | Report both halves of the repo's rhiza state: is `template.yml` valid, and what did the last sync record. `--files` lists managed files as a tree; `--check` compares the pinned ref against the latest release. |
| [`/rhiza:maffay`](skills/maffay.md) | Return a bonmot from a random Peter Maffay song. Takes an optional theme keyword. Needs no repo at all. |

## Destructive

| Command | What it does |
| --- | --- |
| [`/rhiza:detach`](skills/detach.md) | Detach the repo from rhiza: delete every rhiza-managed file listed in `.rhiza/template.lock`, prune the emptied directories, and remove the lock. Prompts for confirmation unless `--force` is passed. Detaches a repo, not the plugin. |

## Internals

Not slash commands. These are **internal procedures** in the plugin's `prompts/`
directory — deliberately outside `skills/` so they can't be invoked directly.
`/rhiza:init` and `/rhiza:update` read and follow them, and most are backed by a
deterministic, stdlib-only script under `scripts/`. Documented here because their
behaviour is part of what those commands do to your repo.

| Procedure | What it does | Script |
| --- | --- | --- |
| [install-uv](internals/install-uv.md) | Make sure `uv` is installed — the first step of both `/init` and `/update`. | — |
| [pr-base](internals/pr-base.md) | A work branch off an up-to-date default, which is never pushed to. | — |
| [skeleton](internals/skeleton.md) | `uv init --lib`, then the `[project]` shape the template's gates require. | `init_skeleton.py` |
| [license](internals/license.md) | SPDX `license`/`license-files` metadata + the `LICENSE` file. | `set_license.py` |
| [python-version](internals/python-version.md) | Pin `requires-python`, rewrite the Python classifiers, sync `.python-version`. | `set_python_version.py` |
| [design-analysis](internals/design-analysis.md) | Complexity and architecture evidence that no `make` gate measures. | — |
| [scorecard](internals/scorecard.md) | The 1–10 rubric, the scoping rule, findings and the issue menu. | — |

## The long form

Everything above, at length and with worked examples:
**[An introduction to rhiza-claude](paper/rhiza-claude-intro.pdf)** (PDF).

It covers the two-repository boundary a sync respects, what "rhiza-managed" means on
disk, installation, a worked first run from an empty directory to a scored repository,
why the commands are prose rather than code, and how the design compares against
shipping an MCP server. The figures in it are captured command output, not mock-ups.

The PDF is rebuilt from `paper/rhiza-claude-intro.tex` on every commit, so it never
lags the plugin it describes.
