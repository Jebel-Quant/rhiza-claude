#!/usr/bin/env python3
"""Scaffold a new rhiza-managed project's non-synced starter files.

A stdlib-only port of the project-scaffolding that `rhiza init` performs in
rhiza-cli (`rhiza.commands._init_helpers`), bundled with this plugin so
`/rhiza:init` can create a repo without the `rhiza` CLI's `init` command — the
long-term goal being to retire `rhiza init` entirely.

`rhiza sync` delivers the shared infrastructure (CI, `.rhiza/rhiza.mk`,
`docs/mkdocs-base.yml`, `ruff.toml`, `pytest.ini`, …). This script writes only
the files sync does **not** own and that a fresh project needs:

  .rhiza/template.yml   the sync config (repository/ref/profile)
  Makefile              a bootstrap Makefile whose `sync` target self-installs
                        rhiza until the first sync writes `.rhiza/rhiza.mk`
  pyproject.toml        satisfies the template's `.rhiza/tests/test_pyproject.py`
  src/<pkg>/…           __init__.py + main.py (docstringed, for test_docstrings)
  tests/test_main.py    example tests importing the package
  mkdocs.yml            INHERITs docs/mkdocs-base.yml (delivered by sync)
  README.md             a real starter README (test_readme_validation passes it)

Every file is created **only if absent** — existing files are left untouched.
The jinja2 templates from rhiza-cli are reproduced here as plain string
templates so this stays dependency-free like the other bundled scripts.

Usage:
  python3 scripts/init_scaffold.py [TARGET] --project-name NAME --owner OWNER \
      [--host github|gitlab] [--language python|go] \
      [--template-repo owner/repo] [--ref TAG] \
      [--components package,mkdocs,readme] [--json]

`.rhiza/template.yml` and `Makefile` are always written; `--components` selects
from the optional set {package, mkdocs, readme} (a Python-only set — `go`
scaffolds only README). Creating `package` also runs `uv lock` when `uv` is
available.
"""

from __future__ import annotations

import argparse
import json
import keyword
import re
import subprocess  # nosec B404
import sys
from pathlib import Path

DEFAULT_TEMPLATE_REPO = {"python": "jebel-quant/rhiza", "go": "jebel-quant/rhiza-go"}
OPTIONAL_COMPONENTS = ("package", "mkdocs", "readme")
DEFAULT_DESCRIPTION = "Add your description here."

_HOSTS = {
    "github": ("github.com", "github.io"),
    "gitlab": ("gitlab.com", "gitlab.io"),
}

# --- string templates (ported from rhiza-cli's _templates/basic/*.jinja2) ----

_PYPROJECT = """\
[build-system]
requires = ["hatchling>=1.29"]
build-backend = "hatchling.build"

[project]
name = "__PROJECT_NAME__"
version = "0.1.0"
description = "__DESCRIPTION__"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
license-files = ["LICENSE"]
authors = [
  { name = "__OWNER__" }
]
keywords = []
classifiers = [
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
    "License :: OSI Approved :: MIT License",
    "Intended Audience :: Developers",
]
dependencies = []

[project.urls]
Homepage = "https://__REPO_HOST__/__OWNER__/__PROJECT_NAME__"
Repository = "https://__REPO_HOST__/__OWNER__/__PROJECT_NAME__"

[tool.hatch.build.targets.wheel]
packages = ["src/__PACKAGE_NAME__"]

[dependency-groups]
test = [
    "pytest>=8.0.0",
    "pytest-cov>=6.0.0",
    "pytest-xdist>=3.0.0",
]
lint = [
    "ruff>=0.11.0",
]
dev = []
"""

_INIT_PY = '"""__PROJECT_NAME__."""\n'

_MAIN_PY = '''\
"""Main module for __PROJECT_NAME__."""


def say_hello(name: str) -> str:
    """Say hello to the user.

    Args:
        name: The name of the user.

    Returns:
        A greeting string.
    """
    return f"Hello, {name}!"


def main() -> None:
    """Execute the main function."""
    print(say_hello("World"))
'''

_TEST_MAIN_PY = '''\
"""Tests for __PACKAGE_NAME__.main module."""

from __PACKAGE_NAME__.main import main, say_hello


def test_say_hello():
    """Test say_hello with default name."""
    assert say_hello("World") == "Hello, World!"


def test_say_hello_custom_name():
    """Test say_hello with a custom name."""
    assert say_hello("Alice") == "Hello, Alice!"


def test_main_prints_hello_world(capsys):
    """Test that main prints Hello, World! to stdout."""
    main()
    captured = capsys.readouterr()
    assert captured.out == "Hello, World!\\n"
'''

_MKDOCS = """\
INHERIT: docs/mkdocs-base.yml

site_name: __PROJECT_NAME__
site_description: __DESCRIPTION__
site_url: https://__OWNER__.__PAGES_HOST__/__PROJECT_NAME__/
repo_url: https://__REPO_HOST__/__OWNER__/__PROJECT_NAME__
repo_name: __OWNER__/__PROJECT_NAME__
edit_uri: edit/main/

docs_dir: docs

nav:
  - Home: index.md
  - Reports:
      - Test Report: reports/html-report/report.html
      - Coverage Report: reports/html-coverage/index.html
"""

# The bootstrap Makefile: its `sync` target self-installs rhiza via uvx and is
# active only until the first sync writes `.rhiza/rhiza.mk`, which then takes
# over. This is what makes `make sync` work on a brand-new repo.
_MAKEFILE = """\
## Makefile (repo-owned)
# Keep this file small. It can be edited without breaking template sync.

# Bootstrap sync: active only before .rhiza/rhiza.mk is written by first sync
ifeq ($(wildcard .rhiza/rhiza.mk),)
.PHONY: sync
sync: ## Sync with template repository as defined in .rhiza/template.yml
\tuvx rhiza sync .
endif

# Include the Rhiza API (template-managed, optional on first run)
-include .rhiza/rhiza.mk

# Optional: developer-local extensions (not committed)
-include local.mk
"""

# A real starter README. The Usage snippet is tagged +RHIZA_SKIP so the
# template's README validation (test_readme_validation.py) does not try to
# execute it against a not-yet-installed src-layout package.
_README = """\
# __PROJECT_NAME__

__DESCRIPTION__

## Installation

Install the project and its dependencies with \
[uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

## Usage

```python +RHIZA_SKIP
from __PACKAGE_NAME__.main import say_hello

print(say_hello("World"))
```

---

Scaffolded by [`rhiza`](https://github.com/jebel-quant/rhiza). Run
`/rhiza:revisit` to flesh this out with the full badge set and project docs.
"""


def normalize_package_name(name: str) -> str:
    """Normalise a string into a valid Python package identifier."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if name and name[0].isdigit():
        name = f"_{name}"
    if keyword.iskeyword(name):
        name = f"{name}_"
    return name


def profile_for_host(host: str) -> str:
    """Return the sync profile matching the git hosting platform."""
    return "gitlab-project" if host == "gitlab" else "github-project"


def render_template_yml(repo: str, ref: str, host: str, language: str) -> str:
    """Render `.rhiza/template.yml` (mirrors template.yml.jinja2)."""
    lines = [f'repository: "{repo}"', f'ref: "{ref}"']
    if host == "gitlab":
        lines.append("template-host: gitlab")
    if language != "python":
        lines.append(f"language: {language}")
    lines += ["", "profiles:", f"  - {profile_for_host(host)}", ""]
    return "\n".join(lines)


def _fill(template: str, **subs: str) -> str:
    """Replace __TOKEN__ placeholders in a template body."""
    out = template
    for key, value in subs.items():
        out = out.replace(f"__{key}__", value)
    return out


def render_pyproject(
    project_name: str, package_name: str, owner: str, repo_host: str, description: str
) -> str:
    return _fill(
        _PYPROJECT,
        PROJECT_NAME=project_name,
        PACKAGE_NAME=package_name,
        OWNER=owner,
        REPO_HOST=repo_host,
        DESCRIPTION=description,
    )


def render_mkdocs(
    project_name: str, owner: str, repo_host: str, pages_host: str, description: str
) -> str:
    return _fill(
        _MKDOCS,
        PROJECT_NAME=project_name,
        OWNER=owner,
        REPO_HOST=repo_host,
        PAGES_HOST=pages_host,
        DESCRIPTION=description,
    )


def render_readme(project_name: str, package_name: str, description: str) -> str:
    return _fill(
        _README, PROJECT_NAME=project_name, PACKAGE_NAME=package_name, DESCRIPTION=description
    )


def _write_if_absent(
    path: Path, content: str, created: list[str], skipped: list[str], target: Path
) -> None:
    """Write *content* to *path* only when it does not already exist."""
    rel = str(path.relative_to(target)) if path.is_relative_to(target) else str(path)
    if path.exists():
        skipped.append(rel)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    created.append(rel)


def _run_uv_lock(target: Path, notes: list[str]) -> None:
    """Generate uv.lock via `uv lock`, skipping gracefully if uv is missing."""
    if (target / "uv.lock").exists():
        return
    try:
        result = subprocess.run(  # nosec B603 B607
            ["uv", "lock"],  # noqa: S607
            cwd=target,
            capture_output=True,
            text=True,
        )
    except (OSError, FileNotFoundError):
        notes.append("uv not found — skipped uv.lock (run `uv lock` manually)")
        return
    if result.returncode == 0:
        notes.append("ran `uv lock` → uv.lock")
    else:
        notes.append(f"`uv lock` failed (exit {result.returncode}) — skipped uv.lock")


def scaffold(
    target: Path,
    *,
    project_name: str,
    package_name: str,
    owner: str,
    host: str,
    language: str,
    template_repo: str,
    ref: str,
    components: list[str],
    description: str = DEFAULT_DESCRIPTION,
) -> dict:
    """Write the starter files; return a summary dict."""
    repo_host, pages_host = _HOSTS.get(host, _HOSTS["github"])
    created: list[str] = []
    skipped: list[str] = []
    notes: list[str] = []

    # Always: template.yml + bootstrap Makefile.
    _write_if_absent(
        target / ".rhiza" / "template.yml",
        render_template_yml(template_repo, ref, host, language),
        created,
        skipped,
        target,
    )
    _write_if_absent(target / "Makefile", _MAKEFILE, created, skipped, target)

    want = set(components)
    if language == "go":
        # Mirror rhiza init: Go projects get only a README here; the Go package
        # is the user's to create.
        want &= {"readme"}
        if "go mod init" not in " ".join(notes):
            notes.append(
                f"go: run `go mod init {repo_host}/{owner}/{project_name}` to start the module"
            )

    if "package" in want and language == "python":
        pkg_dir = target / "src" / package_name
        _write_if_absent(
            pkg_dir / "__init__.py",
            _fill(_INIT_PY, PROJECT_NAME=project_name),
            created,
            skipped,
            target,
        )
        _write_if_absent(
            pkg_dir / "main.py",
            _fill(_MAIN_PY, PROJECT_NAME=project_name),
            created,
            skipped,
            target,
        )
        _write_if_absent(
            target / "tests" / "test_main.py",
            _fill(_TEST_MAIN_PY, PACKAGE_NAME=package_name),
            created,
            skipped,
            target,
        )
        _write_if_absent(
            target / "pyproject.toml",
            render_pyproject(project_name, package_name, owner, repo_host, description),
            created,
            skipped,
            target,
        )
        _run_uv_lock(target, notes)

    if "mkdocs" in want and language == "python":
        _write_if_absent(
            target / "mkdocs.yml",
            render_mkdocs(project_name, owner, repo_host, pages_host, description),
            created,
            skipped,
            target,
        )

    if "readme" in want:
        _write_if_absent(
            target / "README.md",
            render_readme(project_name, package_name, description),
            created,
            skipped,
            target,
        )

    return {
        "target": str(target),
        "project_name": project_name,
        "package_name": package_name,
        "language": language,
        "template_repository": template_repo,
        "ref": ref,
        "profile": profile_for_host(host),
        "created": created,
        "skipped": skipped,
        "notes": notes,
    }


def _parse_components(raw: str | None, language: str) -> list[str]:
    """Resolve the --components value to a validated list."""
    if raw is None:
        return list(OPTIONAL_COMPONENTS)
    items = [c.strip() for c in raw.split(",") if c.strip()]
    unknown = [c for c in items if c not in OPTIONAL_COMPONENTS]
    if unknown:
        choices = ", ".join(OPTIONAL_COMPONENTS)
        raise ValueError(f"unknown component(s): {', '.join(unknown)}; choose from {choices}")
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a new rhiza-managed project's non-synced starter files.",
    )
    parser.add_argument(
        "target", nargs="?", default=".", help="Repository root (default: current directory)."
    )
    parser.add_argument("--project-name", help="Project name (default: target directory name).")
    parser.add_argument(
        "--package-name", help="Python package name (default: normalized project name)."
    )
    parser.add_argument(
        "--owner", default="your-org", help="GitHub/GitLab owner or org (default: your-org)."
    )
    parser.add_argument(
        "--host", choices=("github", "gitlab"), default="github", help="Git hosting platform."
    )
    parser.add_argument(
        "--language", choices=("python", "go"), default="python", help="Project language."
    )
    parser.add_argument(
        "--template-repo", help="Template repository owner/repo (default: by language)."
    )
    parser.add_argument("--ref", default="main", help="Template branch/tag (default: main).")
    parser.add_argument(
        "--description", default=DEFAULT_DESCRIPTION, help="Short project description."
    )
    parser.add_argument(
        "--components",
        help=f"Comma list from {{{', '.join(OPTIONAL_COMPONENTS)}}}; default: all applicable.",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit the summary as JSON."
    )
    args = parser.parse_args(argv)

    target = Path(args.target).resolve()
    project_name = args.project_name or target.name
    package_name = args.package_name or normalize_package_name(project_name)
    template_repo = args.template_repo or DEFAULT_TEMPLATE_REPO[args.language]
    try:
        components = _parse_components(args.components, args.language)
    except ValueError as exc:
        parser.error(str(exc))

    summary = scaffold(
        target,
        project_name=project_name,
        package_name=package_name,
        owner=args.owner,
        host=args.host,
        language=args.language,
        template_repo=template_repo,
        ref=args.ref,
        components=components,
        description=args.description,
    )

    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        for path in summary["created"]:
            print(f"created  {path}")
        for path in summary["skipped"]:
            print(f"skipped  {path} (already exists)", file=sys.stderr)
        for note in summary["notes"]:
            print(f"note     {note}", file=sys.stderr)
        if not summary["created"]:
            print("nothing to create — all target files already exist", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
