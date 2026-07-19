# Contributing to rhiza-claude

Thanks for your interest in improving **rhiza-claude** — the Claude Code plugin
providing the `rhiza` slash commands. Contributions of all kinds are welcome.

By participating you agree to abide by our
[Code of Conduct](./CODE_OF_CONDUCT.md).

## What's in here

| Path | Purpose |
| --- | --- |
| `commands/` | The plugin's slash commands — one Markdown prompt per command. |
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
make lint         # pre-commit across every file (ruff, mypy, interrogate, test-layout, manifest checks, …)
make test         # pytest with a 100% coverage gate on scripts/
make book         # build the docs site locally
```

`make lint` runs every quality hook (mypy, interrogate, the test-layout check,
and the manifest JSON/version-parity checks included). To run just one, use
`uvx pre-commit run <hook-id> --all-files`.

The CI gates mirror these exactly, so a green `make lint && make test` locally
means a green PR.

### Adding or changing a command

1. Edit (or add) the prompt file under `commands/<name>.md`. Keep the
   frontmatter (`description`, `argument-hint`, `allowed-tools`) accurate.
2. If the command is backed by a script, put the logic in
   `scripts/<name>.py` (stdlib-only) and cover it in `tests/test_<name>.py` —
   the suite enforces **100% coverage**, strict **mypy**, and **100% docstring**
   coverage on `scripts/`.
3. Give the command a page under `docs/commands/<name>.md` and add it to the
   `nav` in `mkdocs.yml`.
4. Update `README.md` if it's a headline command.

## Commit and PR conventions

- Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `chore:`, `test:`, `docs:`, …) — the changelog is generated
  from them (`make changelog`).
- Branch off `main`, open a PR, and let CI run. Keep PRs focused.
- Never bump the plugin version by hand in only one manifest — the two must
  match (a pre-commit hook enforces it); use `uv run --python 3.12 --no-project python scripts/bump_version.py`.

## Reporting bugs / requesting features

Open an issue on the
[tracker](https://github.com/Jebel-Quant/rhiza-claude/issues). For security
reports, see [SECURITY.md](./SECURITY.md) instead of a public issue.
