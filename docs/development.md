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
make book        # build the documentation site into _book/
make book-serve  # serve the docs locally with live reload
make clean       # remove generated caches and artifacts
```

`make lint` runs every quality hook — mypy, interrogate (docstrings), the
test-layout check, the manifest JSON/version-parity checks, and the three that
gate the prose (`command-contracts`, `prompt-wiring`, `docs-nav`). To run a
single one, use `uvx pre-commit run <hook-id> --all-files` (e.g. `mypy`,
`interrogate`, `test-layout`, `manifest-version-parity`, `docs-nav`).

The prose hooks are the unusual ones. `command-contracts` treats each command as
a contract — its frontmatter parses, its bash blocks are valid shell, the scripts
and flags it names exist, and exactly the destructive commands
(`release`, `uninstall`) declare `disable-model-invocation: true`. `prompt-wiring`
keeps the `prompts/` procedures referenced and un-invocable. `docs-nav` requires a
`docs/` page and an `mkdocs.yml` nav entry for every command and procedure, in
both directions, so neither an undocumented command nor an orphaned page can ship.

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
uvx pytest tests/ -k e2e -q  # just the end-to-end tests (needs network, uv, cargo)
```

**The end-to-end tests are not opt-in.** They scaffold repos with the real `/init`
script chain, sync them from the real template, and assert the outcomes — a Python
repo on `github-project`, one on `gitlab-project`, and a Rust crate. They used to be
opt-in behind `RHIZA_E2E=1`, which is how `/rhiza:quality` shipped unable to run at
all: a suite nobody runs still reads as coverage.

The template ref they sync from is **pinned** in `tests/conftest.py`
(`PINNED_TEMPLATE_REF`), so a PR run never goes red merely because upstream released.
The cost of pinning is drift, so `.github/workflows/template-drift.yml` runs the same
tests weekly against the template's *latest* release and files a finding when the two
disagree. A red **Template drift** means upstream moved; a red **CI** means this repo
did.

Two things need tools the plugin itself does not: the Rust fixtures need `cargo`
(`cargo init --lib` builds the crate), and half of `tests/test_platform_cli.py` needs
`glab`. Both skip when the tool is absent, and CI installs or verifies both so the skip
never happens there. Nothing else skips: the pin is a rhiza release that defines every
profile `/rhiza:init` writes, so a ref that stops defining one **fails** the suite rather
than quietly narrowing it.

## CI/CD

- **CI** (`.github/workflows/ci.yml`) runs pre-commit (including a strict
  `mypy` type-check and 100% `interrogate` docstring coverage of `scripts/`)
  and the test suite under the 100% coverage gate.
- **Book** (`.github/workflows/book.yml`) builds the site on every push and
  deploys it to GitHub Pages from the default branch.
- **CodeQL** (`.github/workflows/codeql.yml`) scans the Python scripts and the
  workflows for security issues.
- **Scorecard** (`.github/workflows/scorecard.yml`) runs the OpenSSF Scorecard
  supply-chain analysis and publishes the score (README badge).
