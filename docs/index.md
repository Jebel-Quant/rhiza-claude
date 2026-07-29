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

**rhiza** is the shared original: a *template repository*
([`jebel-quant/rhiza`](https://github.com/jebel-quant/rhiza) for Python,
`rhiza-go` for Go) holding that scaffolding once. **rhiza-claude** — this plugin — is
how a repo adopts it, keeps up with it, and gets told how it's doing: it syncs your
repo from a pinned template release and scores the result.

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
[`/rhiza:status`](commands/status.md) reports both halves, and why
[`/rhiza:quality`](commands/quality.md) checks for `.rhiza/template.yml` **and**
`.rhiza/rhiza.mk` before it runs: every gate it scores is a `make` target the sync
delivers, so scoring an unsynced repo would report it as broken rather than as
unsynced. (By contrast [`/rhiza:release`](commands/release.md) requires neither — it
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

- **`commands/*.md` → slash commands** you invoke: seven of them, each with a page here.
- **`prompts/*.md` → internal procedures**: seven shared steps a command reaches with
  the `Read` tool, deliberately kept *outside* `commands/` so they cannot be invoked
  directly.

Procedures are not implementation trivia — they're where the shared behaviour lives, so
`init.md` alone doesn't explain what `/rhiza:init` does. Installing `uv`, choosing a
work branch, scaffolding a `pyproject.toml`, writing a licence, gathering design
evidence, applying the scoring rubric: all of that is a procedure, which is exactly why
`/init` and `/update` behave identically where they overlap. They're documented under
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
- `/rhiza:release` when you want to cut a version. It needs no `.rhiza/` at all.

## Commands

These are the AI-driven workflow commands. Each has its own page.

| Command | What it does |
| --- | --- |
| [`/rhiza:init`](commands/init.md) | Make the repo rhiza-managed: write `.rhiza/template.yml`, delegate the skeleton + license, open a PR. |
| [`/rhiza:update`](commands/update.md) | Sync to the latest template release and open a PR with **only** template-owned files. |
| [`/rhiza:quality`](commands/quality.md) | Run the code-quality gate and score the repo 1–10 across eight categories. |
| [`/rhiza:docs`](commands/docs.md) | Create or refresh `README.md`, `CLAUDE.md`, and `mkdocs.yml`. |
| [`/rhiza:release`](commands/release.md) | Prepare a release: pick the next version from a table, bump, changelog, commit, tag (no push). |

## Repo utilities

Thin, **read-only**, stdlib-only commands backed by bundled scripts — they read
`.rhiza/template.lock` / `.rhiza/template.yml` directly and work without the
`rhiza` CLI installed. Neither writes anything.

| Command | What it does |
| --- | --- |
| [`/rhiza:status`](commands/status.md) | Report both halves of the repo's rhiza state: is `template.yml` valid, and what did the last sync record. `--files` lists managed files as a tree; `--check` compares the pinned ref against the latest release. |
| [`/rhiza:maffay`](commands/maffay.md) | Return a bonmot from a random Peter Maffay song. Takes an optional theme keyword. Needs no repo at all. |

## Destructive

| Command | What it does |
| --- | --- |
| [`/rhiza:uninstall`](commands/uninstall.md) | Delete every rhiza-managed file listed in `.rhiza/template.lock`, prune the emptied directories, and remove the lock. Prompts for confirmation unless `--force` is passed. |

## Internals

Not slash commands. These are **internal procedures** in the plugin's `prompts/`
directory — deliberately outside `commands/` so they can't be invoked directly.
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
