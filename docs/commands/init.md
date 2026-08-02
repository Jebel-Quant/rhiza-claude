# `/rhiza:init`

Make the current folder a **rhiza-managed repo** by establishing **one file** —
`.rhiza/template.yml`, the pointer that says which template repository this repo
follows and at which ref — and deliver it as a PR.

```
/rhiza:init [repo name]
```

The optional argument is the repository name; it defaults to the current folder's
name.

**`/init` writes one file itself; everything else it delegates.** The only file it
authors is `.rhiza/template.yml`. It creates no CI, no docs, and no starter module,
and it runs no gates, tests, or sync:

| what | who |
| --- | --- |
| `uv` on the machine | [install-uv](../internals/install-uv.md) *(internal)* |
| skeleton + the `pyproject.toml` shape the gates need | [skeleton](../internals/skeleton.md) *(internal)* |
| `requires-python` + classifiers | [python-version](../internals/python-version.md) *(internal)* |
| SPDX metadata + the `LICENSE` file | [license](../internals/license.md) *(internal)* |
| template content (CI, `.rhiza/rhiza.mk`, `Makefile`, docs base) | [`/rhiza:update`](update.md)'s sync |
| first real module + test | you |
| `README.md`, `CLAUDE.md`, `mkdocs.yml` | [`/rhiza:docs`](docs.md) |

The *internal* rows are procedures under the plugin's `prompts/` directory, not slash
commands — `/init` reads and follows them, and you can't invoke them yourself.

So a new repo is **two PRs**: **#1 (`/init`)** makes it rhiza-managed; **#2
(`/update`, run after #1 merges)** pulls the template content. Keeping the sync out of
`/init` stops it re-implementing `/update`.

## What it does

1. **Checks preconditions** — if a `.rhiza/` directory already exists the repo is
   already managed, so `/init` **hands off to [`/rhiza:update`](update.md)** (never
   touching an existing `template.yml`) and stops. Otherwise it runs `git init -b
   main` if there's no repo yet, and always follows
   [install-uv](../internals/install-uv.md) — a one-line no-op when `uv` is already
   installed, and otherwise your prompt to install it.
2. **Settles platform, owner, and name** — all three are derived from an existing
   `origin` remote when there is one (no questions asked); otherwise it asks GitHub
   vs GitLab, the owner/namespace, the name, and the visibility. It then checks the
   platform CLI is logged in with `scripts/platform_cli.py auth-status`, which picks
   `gh auth status` or `glab auth status` for you; not being logged in doesn't stop the
   local work, it just defers the remote steps.
3. **Picks the template repo and ref** — language (`python`, `rust` or `go`) selects
   the profile; the template is `jebel-quant/rhiza` for all three, since it is
   multi-language, and is overridable with any `owner/repo` fork; it
   checks the repo is reachable and pins the ref to its latest release. Nothing is
   synced from it here — that's just the initial pin, which `/update` bumps later.

    It then checks, with `scripts/check_template_profile.py`, that the pinned ref
    actually **defines the profile** the pointer is about to name, and stops rather than
    writing one it doesn't. That check exists because the failure lands so far from the
    mistake: a pointer naming an undefined profile is written happily, merges happily,
    and then kills the *first* `/rhiza:update` with "Profile 'X' was not found". If the
    profile is missing you're offered the choices its output supports — pin a ref that
    does define it, pick one it lists, or wait for a release. A template that can't be
    read at all (offline, unknown ref) is a warning, not a stop: nothing was learned
    either way.
4. **Writes the pointer** via `scripts/init_scaffold.py` — `.rhiza/template.yml` and
   only that, and only if absent — on a `rhiza_init_<date>` branch. It **never**
   pushes to the default branch: for a brand-new repo it asks you to create it,
   initialised with an empty README, as the PR base rather than pushing one itself.
5. **Follows the [skeleton](../internals/skeleton.md) and
   [license](../internals/license.md) procedures**, then verifies a `pyproject.toml`
   exists — without one, `/update`'s gates can't run at all — commits what they
   produced, and **opens the PR**.

After merging, **run [`/rhiza:update`](update.md)** to sync the template (PR #2).

## Prerequisites

[`uv`](https://docs.astral.sh/uv/) — it runs the bundled scripts under a pinned
Python. You don't need to install it beforehand: `/init` follows
[install-uv](../internals/install-uv.md) on every invocation, which is a one-line
no-op if `uv` is already there and otherwise offers to install it.

## Notes

- Only for repos that **aren't** rhiza-managed yet; an existing `.rhiza/` routes
  to [`/rhiza:update`](update.md).
- `/init` never overwrites anything, so running it in an empty folder and in a mature
  repo are the same case.
