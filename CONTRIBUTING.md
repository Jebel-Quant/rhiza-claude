# Contributing to rhiza-claude

Thanks for your interest in improving **rhiza-claude** — the Claude Code plugin
providing the `rhiza` slash commands. Contributions of all kinds are welcome.

By participating you agree to abide by our
[Code of Conduct](./CODE_OF_CONDUCT.md).

## What's in here

| Path | Purpose |
| --- | --- |
| `skills/` | The plugin's slash commands — `<name>/SKILL.md`, the directory naming the command. |
| `scripts/` | Bundled, stdlib-only Python backing the commands (tested). |
| `tests/` | The pytest suite for `scripts/`. |
| `docs/` | The MkDocs documentation site. |
| `.claude-plugin/` | The plugin + marketplace manifests. |

## Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** — used via `uvx` for every tool (nothing
  to install globally).

## Development workflow

Everything is driven by `make` (run `make help` for the full list):

```bash
make help           # show this list
make install        # install the rhiza plugin via the Claude Code CLI
make lint           # run all prek hooks against every file
make test           # run the script test suite with a 100% coverage gate
make e2e            # run only the end-to-end tests, without the coverage gate
make portable       # run everything except them, without the coverage gate
make mutate         # mutation-test the sync core in an isolated worktree (slow)
make book           # build the documentation site into _book/
make book-serve     # serve the docs locally with live reload
make paper          # build the LaTeX paper and stage it for the docs site
make paper-figures  # regenerate the paper's figures from captured command output
make clean          # remove generated caches and artifacts
make changelog      # regenerate CHANGELOG.md from conventional commits
```

`make lint` runs every quality hook (mypy, interrogate, the test-layout check,
and the manifest JSON/version-parity checks included). To run just one, use
`uvx prek run <hook-id> --all-files`.

The runner is [`prek`](https://prek.j178.dev/) — a drop-in reimplementation of
`pre-commit`. The config keeps the `.pre-commit-config.yaml` name and schema, so you
need nothing installed beyond `uv`; `uvx` fetches prek on first use. Bump hook
revisions with `uvx prek update`.

The two you need before opening a PR are `make lint` and `make test` — a green
pair locally means a green PR on everything you can reproduce locally.

The one CI gate you *can't* reproduce is `cross-platform`, which runs `make
portable` on macOS and Windows. Only the platform you're on is reachable from
your machine, so treat a red Windows leg as information rather than a surprise:
it is there to catch the path handling the Linux jobs cannot see.

**`make book` needs a LaTeX engine.** It depends on `paper` (and on `test`), so a
checkout without [`tectonic`](https://tectonic-typesetting.github.io/) or
`pdflatex` fails there rather than in the docs build. That dependency is
deliberate — `docs/index.md` links the PDF and `mkdocs build --strict` fails on a
missing target, so the paper cannot go stale unnoticed. If you're only changing
prose or scripts, `make lint && make test` is enough.

### Adding or changing a command

1. Edit (or add) the prompt file. New commands go in `skills/<name>/SKILL.md`, the
   layout the plugin docs now recommend. Keep the frontmatter (`description`, `argument-hint`,
   `allowed-tools`) accurate, and don't add a `name:` field — in a plugin skill it
   overrides the command name. Never leave a command in both layouts — rule 10 of
   `check_command_contracts.py` fails the build, because which file answers
   `/rhiza:<name>` is then undefined.
2. If the command is backed by a script, put the logic in
   `scripts/<name>.py` (stdlib-only) and cover it in `tests/scripts/test_<name>.py` —
   the suite enforces **100% coverage**, strict **mypy**, and **100% docstring**
   coverage on `scripts/`.
3. Give the command a page under `docs/skills/<name>.md` and add it to the
   `nav` in `mkdocs.yml`. Write the **prose** — what the command is for, and why.
   Don't hand-write the facts that come from the frontmatter (invocation,
   allowed-tools, model-invocability): run
   `uv run --python 3.12 --no-project python plugin/scripts/render_command_docs.py` and it
   appends a **Reference** block for those. The `docs-reference-blocks` hook fails
   if it's stale, so a renamed argument can't linger in the docs.
4. Update `README.md` if it's a headline command.

## Commit and PR conventions

- Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `chore:`, `test:`, `docs:`, …) — the changelog is generated
  from them (`make changelog`).
- Branch off `main`, open a PR, and let CI run. Keep PRs focused.
- Never bump the plugin version by hand — `.claude-plugin/plugin.json` and
  `.claude-plugin/marketplace.json` must agree, and the `manifest-version-parity`
  hook enforces it. Both are declared in `[tool.bumpversion]`
  (`.bumpversion.toml`), so `bump-my-version` writes them together; `/rhiza:release`
  drives it and regenerates the changelog.

## Reporting bugs / requesting features

Open an issue on the
[tracker](https://github.com/Jebel-Quant/rhiza-claude/issues). For security
reports, see [SECURITY.md](./SECURITY.md) instead of a public issue.
