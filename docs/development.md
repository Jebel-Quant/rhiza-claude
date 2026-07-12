# Development

The plugin's slash commands are Markdown prompt files under `commands/`; the
stdlib-only scripts they call live under `scripts/`, with tests under `tests/`.

## Layout

| Path | Purpose |
| --- | --- |
| `.claude-plugin/marketplace.json` | Marketplace manifest listing the `rhiza` plugin. |
| `.claude-plugin/plugin.json` | The `rhiza` plugin manifest. |
| `commands/` | The plugin's slash commands (one `.md` per command). |
| `scripts/` | Bundled stdlib-only Python scripts backing the commands. |
| `tests/` | Pytest suite for the scripts. |
| `docs/` | This book. |

## Make targets

```bash
make help        # list targets
make lint        # run pre-commit against every file
make test        # run the script test suite (100% coverage gate)
make types       # strict mypy type-check of scripts/
make validate    # validate the plugin manifests (JSON + version parity)
make stats       # print the stats dashboard + write docs/stats.html
make book        # build the documentation site into _book/
make book-serve  # serve the docs locally with live reload
make clean       # remove generated caches and artifacts
```

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
make test                          # fast, offline; enforces 100% coverage of scripts/
RHIZA_E2E=1 uvx pytest tests/test_init_e2e.py   # opt-in end-to-end (needs network + uv)
```

The end-to-end test scaffolds a repo, runs a real `rhiza sync`, and asserts the
template's own gates pass — the sign-off for changes to the `init` scaffolder.

## CI/CD

- **CI** (`.github/workflows/ci.yml`) runs pre-commit (including a strict
  `mypy` type-check of `scripts/`) and the test suite under the 100% coverage
  gate.
- **Book** (`.github/workflows/book.yml`) builds the site on every push and
  deploys it to GitHub Pages from the default branch.
- **CodeQL** (`.github/workflows/codeql.yml`) scans the Python scripts and the
  workflows for security issues.
- **Scorecard** (`.github/workflows/scorecard.yml`) runs the OpenSSF Scorecard
  supply-chain analysis and publishes the score (README badge).
